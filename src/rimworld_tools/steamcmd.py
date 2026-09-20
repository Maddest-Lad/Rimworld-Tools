from __future__ import annotations

import asyncio
import io
import logging
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

from . import acf, paths, symlink
from . import cache as cache_mod
from .config import RIMWORLD_APP_ID, STEAMCMD_BATCH_SIZE, Settings

logger = logging.getLogger(__name__)

STEAMCMD_ZIP_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip"

# Beyond this, deep mod asset paths under <mods_dir>/<pfid>/Textures/... start hitting MAX_PATH.
_MODS_DIR_LENGTH_WARN = 120

_LOG_POLL_SECONDS = 0.15
_LOG_EXCERPT_LINES = 200

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_DOWNLOADING_RE = re.compile(r"Downloading item (\d+)")
_SUCCESS_RE = re.compile(r"Success\. Downloaded item (\d+)")
_ERROR_RE = re.compile(r"ERROR! (?:Download item|Timeout downloading item) (\d+)\s*(.*)")
_NOT_LOGGED_ON = "ERROR! Not logged on."
_VPROF_OVERFLOW = "No room for new profile in vprof"


@dataclass
class LogParser:
    """Scrapes per-item results out of SteamCMD's console log.

    SteamCMD's exit code is meaningless (0 with per-item failures), so the pending set is
    the source of truth: an item succeeded only if its Success line was seen.
    """

    pending: set[str]
    succeeded: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    run_errors: list[str] = field(default_factory=list)
    excerpt: list[str] = field(default_factory=list)
    _buffer: str = ""

    def feed(self, text: str) -> None:
        text = _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
        self._buffer += text
        *complete, self._buffer = self._buffer.split("\n")
        for line in complete:
            self._line(line)

    def flush(self) -> None:
        if self._buffer:
            self._line(self._buffer)
            self._buffer = ""

    def _line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        if len(self.excerpt) < _LOG_EXCERPT_LINES:
            self.excerpt.append(line)

        if m := _SUCCESS_RE.search(line):
            pfid = m.group(1)
            self.pending.discard(pfid)
            self.failed.pop(pfid, None)
            if pfid not in self.succeeded:
                self.succeeded.append(pfid)
        elif m := _ERROR_RE.search(line):
            pfid, reason = m.group(1), m.group(2).strip()
            self.pending.discard(pfid)
            self.failed[pfid] = reason or "download failed"
        elif _NOT_LOGGED_ON in line:
            self.run_errors.append("Not logged on — login/network/firewall failure")
        elif _VPROF_OVERFLOW in line:
            self.run_errors.append("vprof overflow — too many items in one invocation")

    def finish(self, reason: str) -> None:
        """Anything still pending at process exit failed, whatever the exit code said."""
        for pfid in sorted(self.pending, key=int):
            self.failed.setdefault(pfid, reason)
        self.pending.clear()


@dataclass
class BatchResult:
    succeeded: list[str]
    failed: dict[str, str]
    run_errors: list[str]
    timed_out: bool
    duration_s: float
    excerpt: list[str]


def resolve_mods_dir(settings: Settings) -> Path | None:
    if settings.mods_dir is not None:
        return settings.mods_dir
    found = paths.discover(settings).mods_dir
    return Path(found.path) if found else None


def is_installed(settings: Settings) -> bool:
    return settings.steamcmd_exe.is_file()


def _extract_zip_safely(archive: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if root not in target.parents and target != root:
                raise ValueError(f"zip entry escapes destination: {member.filename}")
            zf.extract(member, dest)


def install(settings: Settings, force: bool = False) -> None:
    """Download and extract SteamCMD into the prefix. No checksum or version pin exists upstream."""
    if is_installed(settings) and not force:
        return
    if force and settings.steamcmd_dir.is_dir():
        symlink.rmtree(settings.steamcmd_dir)
    resp = requests.get(STEAMCMD_ZIP_URL, timeout=(5, 120))
    resp.raise_for_status()
    _extract_zip_safely(resp.content, settings.steamcmd_dir)


def write_script(force_install_dir: Path, pfids: list[str], validate: bool) -> Path:
    """One script per invocation, in a unique temp file so concurrent runs cannot clobber it."""
    suffix = " validate" if validate else ""
    lines = [f'force_install_dir "{force_install_dir}"', "login anonymous"]
    lines += [f"workshop_download_item {RIMWORLD_APP_ID} {pfid}{suffix}" for pfid in pfids]
    lines.append("quit")
    with tempfile.NamedTemporaryFile(
        "w", prefix="steamcmd_", suffix=".txt", delete=False, encoding="utf-8"
    ) as fd:
        fd.write("\n".join(lines) + "\n")
        return Path(fd.name)


def _read_new(log: Path, offset: int, parser: LogParser) -> int:
    try:
        size = log.stat().st_size
    except OSError:
        return offset
    if size < offset:  # rotated or truncated
        offset = 0
    if size == offset:
        return offset
    with log.open("rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
    parser.feed(chunk.decode("utf-8", errors="replace"))
    return offset + len(chunk)


async def _tail(log: Path, offset: int, parser: LogParser, stop: asyncio.Event) -> None:
    # On Windows SteamCMD's stdout does not stream through a pipe, so the log file is
    # the only reliable progress channel.
    while not stop.is_set():
        offset = await asyncio.to_thread(_read_new, log, offset, parser)
        try:
            await asyncio.wait_for(stop.wait(), _LOG_POLL_SECONDS)
        except TimeoutError:
            pass
    await asyncio.to_thread(_read_new, log, offset, parser)
    parser.flush()


async def run_batch(
    settings: Settings, pfids: list[str], validate: bool, timeout_s: float
) -> BatchResult:
    """Run one SteamCMD process for at most STEAMCMD_BATCH_SIZE items."""
    if len(pfids) > STEAMCMD_BATCH_SIZE:
        raise ValueError(f"batch of {len(pfids)} exceeds {STEAMCMD_BATCH_SIZE}")
    settings.force_install_dir.mkdir(parents=True, exist_ok=True)
    script = write_script(settings.force_install_dir, pfids, validate)
    log = settings.console_log
    start_offset = log.stat().st_size if log.is_file() else 0
    parser = LogParser(pending=set(pfids))
    stop = asyncio.Event()
    started = time.monotonic()
    timed_out = False

    proc = await asyncio.create_subprocess_exec(
        str(settings.steamcmd_exe),
        "+runscript",
        str(script),
        cwd=str(settings.steamcmd_dir),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    tail = asyncio.create_task(_tail(log, start_offset, parser, stop))
    try:
        await asyncio.wait_for(proc.wait(), timeout_s)
    except TimeoutError:
        timed_out = True
        proc.kill()
        await proc.wait()
    finally:
        stop.set()
        await tail
        script.unlink(missing_ok=True)

    parser.finish("timed out" if timed_out else "no Success line seen before SteamCMD exited")
    return BatchResult(
        succeeded=parser.succeeded,
        failed=parser.failed,
        run_errors=parser.run_errors,
        timed_out=timed_out,
        duration_s=round(time.monotonic() - started, 1),
        excerpt=parser.excerpt,
    )


async def warm_up(settings: Settings, timeout_s: float = 600) -> bool:
    """First run self-updates SteamCMD and is slow and chatty; do it once, deliberately."""
    proc = await asyncio.create_subprocess_exec(
        str(settings.steamcmd_exe),
        "+quit",
        cwd=str(settings.steamcmd_dir),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout_s)
        return True
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return False


def clear_depot_cache(settings: Settings) -> dict[str, Any]:
    """Stale depotcache manifests cause downloads that 'succeed' but write nothing."""
    cache = settings.depotcache_dir
    if not cache.is_dir():
        return {"cleared": 0, "freed_bytes": 0}
    files = [p for p in cache.iterdir() if p.is_file()]
    freed = sum(p.stat().st_size for p in files)
    symlink.rmtree(cache)
    cache.mkdir()
    return {"cleared": len(files), "freed_bytes": freed}


def _normalise_pfids(raw: list[str | int]) -> tuple[list[str], list[str]]:
    good: list[str] = []
    bad: list[str] = []
    for item in raw:
        s = str(item).strip()
        if s.isdigit() and s not in good:
            good.append(s)
        elif not s.isdigit():
            bad.append(s)
    return good, bad


async def download(
    settings: Settings,
    pfids: list[str | int],
    validate: bool = False,
    clear_cache: bool = False,
    timeout_per_batch_s: float = 900,
) -> dict[str, Any]:
    good, bad = _normalise_pfids(pfids)
    if not good:
        return {"error": "No valid published file ids given.", "hint": "Pass numeric pfids."}
    if len(good) > settings.max_download_items:
        return {
            "error": f"Too many items ({len(good)}); the cap is {settings.max_download_items}.",
            "hint": (
                "Split into smaller calls, or raise RIMWORLD_TOOLS_MAX_DOWNLOAD_ITEMS. "
                "Each call blocks until every item finishes."
            ),
        }
    if not is_installed(settings):
        return {"error": "SteamCMD is not installed.", "hint": "Run steamcmd_setup first."}

    result: dict[str, Any] = {
        "succeeded": [],
        "failed": [{"pfid": b, "reason": "not a numeric published file id"} for b in bad],
        "batches_run": 0,
        "duration_s": 0.0,
        "warnings": [],
    }
    if clear_cache:
        result["depot_cache"] = clear_depot_cache(settings)

    batches = [good[i : i + STEAMCMD_BATCH_SIZE] for i in range(0, len(good), STEAMCMD_BATCH_SIZE)]
    last_excerpt: list[str] = []
    for idx, batch in enumerate(batches):
        br = await run_batch(settings, batch, validate, timeout_per_batch_s)
        result["batches_run"] += 1
        result["duration_s"] += br.duration_s
        result["succeeded"].extend(br.succeeded)
        result["failed"].extend({"pfid": p, "reason": r} for p, r in br.failed.items())
        result["warnings"].extend(br.run_errors)
        last_excerpt = br.excerpt
        if br.timed_out:
            result["warnings"].append(f"batch {idx + 1} timed out after {timeout_per_batch_s}s")
        if any("Not logged on" in e for e in br.run_errors):
            for skipped in batches[idx + 1 :]:
                result["failed"].extend(
                    {"pfid": p, "reason": "not attempted: earlier batch could not log on"}
                    for p in skipped
                )
            result["hint"] = "SteamCMD could not log on anonymously; check network/firewall."
            break

    result["duration_s"] = round(result["duration_s"], 1)
    result["log_excerpt"] = last_excerpt[-40:]
    if result["failed"] and not result.get("hint"):
        result["hint"] = (
            "For failed items: retry with clear_depot_cache=true, then validate=true. "
            "Persistent failures usually mean the item is private, deleted, or not a RimWorld mod."
        )
    return result


def status(settings: Settings) -> dict[str, Any]:
    mods_dir = resolve_mods_dir(settings)
    content = settings.workshop_content_dir
    junction_target = symlink.read_junction(content)
    junction_ok = (
        mods_dir is not None
        and junction_target is not None
        and junction_target.resolve() == mods_dir.resolve()
    )
    acf_count = 0
    acf_present = settings.acf_path.is_file()
    if acf_present:
        try:
            acf_count = len(acf.items(acf.load(settings.acf_path)))
        except (SyntaxError, ValueError, OSError) as exc:
            # A corrupt ACF must not take the health check down.
            logger.warning("could not parse %s: %s", settings.acf_path, exc)

    warnings: list[str] = []
    if mods_dir is None:
        warnings.append("Mods folder not found; set RIMWORLD_TOOLS_MODS_DIR or install RimWorld.")
    elif len(str(mods_dir)) > _MODS_DIR_LENGTH_WARN:
        warnings.append(
            f"Mods path is {len(str(mods_dir))} chars; deep mod assets may exceed MAX_PATH (260)."
        )
    if junction_target is not None and not junction_ok:
        warnings.append(f"Workshop content junction points at {junction_target}, not the Mods dir.")
    elif junction_target is None and content.exists():
        warnings.append("Workshop content path exists but is a real directory, not a junction.")

    return {
        "installed": is_installed(settings),
        "exe_path": str(settings.steamcmd_exe),
        "prefix": str(settings.steamcmd_prefix),
        "mods_dir": str(mods_dir) if mods_dir else None,
        "junction_path": str(content),
        "junction_target": str(junction_target) if junction_target else None,
        "junction_ok": junction_ok,
        "acf_present": acf_present,
        "acf_item_count": acf_count,
        "steam_processes_running": acf.steam_processes_running(),
        "web_api_cache": cache_mod.Cache(settings.cache_dir).stats(),
        "warnings": warnings,
    }


async def setup(
    settings: Settings, force_reinstall: bool = False, force_junction: bool = False
) -> dict[str, Any]:
    mods_dir = resolve_mods_dir(settings)
    if mods_dir is None:
        return {
            "error": "Could not locate the RimWorld Mods folder.",
            "hint": "Set RIMWORLD_TOOLS_MODS_DIR, or check rimworld_locate().",
        }
    settings.steamcmd_dir.mkdir(parents=True, exist_ok=True)
    settings.force_install_dir.mkdir(parents=True, exist_ok=True)

    freshly_installed = force_reinstall or not is_installed(settings)
    try:
        await asyncio.to_thread(install, settings, force_reinstall)
    except (requests.RequestException, ValueError, OSError) as exc:
        return {"error": f"SteamCMD install failed: {exc}", "hint": f"URL: {STEAMCMD_ZIP_URL}"}

    junction = symlink.ensure_junction(settings.workshop_content_dir, mods_dir, force_junction)
    if junction.error:
        return {"error": junction.error, "hint": junction.hint, "status": status(settings)}

    warmed = await warm_up(settings) if freshly_installed else None

    out = status(settings)
    out["junction_created"] = junction.created
    out["freshly_installed"] = freshly_installed
    if warmed is False:
        out["warnings"].append("SteamCMD self-update did not finish within the timeout.")
    return out
