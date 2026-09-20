from __future__ import annotations

import gzip
import io
import json
import logging
import shutil
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from . import symlink
from .config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Source:
    repo: str
    branch: str
    filename: str
    optional: bool = False

    @property
    def zip_url(self) -> str:
        return f"https://github.com/{self.repo}/archive/refs/heads/{self.branch}.zip"


# Branch names differ per repo and are a live 404 hazard; each is resolved individually, and
# sync falls back main<->master if upstream renames.
SOURCES: dict[str, Source] = {
    "steam_db": Source("RimSort/Steam-Workshop-Database", "main", "steamDB.json"),
    "community_rules": Source("RimSort/Community-Rules-Database", "main", "communityRules.json"),
    "use_this_instead": Source("emipa606/UseThisInstead", "master", "replacements.json.gz"),
    "no_version_warning": Source("emipa606/NoVersionWarning", "master", "ModIdsToFix.xml"),
    "rimworld_versions": Source(
        "bukforks/rimworld-versions", "main", "rimworld_versions.json", optional=True
    ),
}

_TIMEOUT = (5, 120)
_USER_RULES_SEED = {"timestamp": 0, "rules": {}}


def _dir(settings: Settings, name: str) -> Path:
    return settings.db_dir / name


def _meta_path(settings: Settings, name: str) -> Path:
    return settings.db_dir / f"{name}.meta.json"


def _read_meta(settings: Settings, name: str) -> dict[str, Any]:
    try:
        return json.loads(_meta_path(settings, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(settings: Settings, name: str, meta: dict[str, Any]) -> None:
    settings.db_dir.mkdir(parents=True, exist_ok=True)
    _meta_path(settings, name).write_text(json.dumps(meta, indent=1), encoding="utf-8")


def locate(settings: Settings, name: str, filename: str | None = None) -> Path | None:
    """Find the DB file inside the extracted tree; repos are free to nest it."""
    root = _dir(settings, name)
    if not root.is_dir():
        return None
    target = (filename or SOURCES[name].filename).lower()
    hits = sorted(p for p in root.rglob("*") if p.is_file() and p.name.lower() == target)
    return hits[0] if hits else None


def _extract_swap(archive: bytes, dest: Path, expected_filename: str) -> None:
    """Validate a uniquely staged archive before replacing the previous database tree."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.", dir=dest.parent))
    backup: Path | None = None
    root = tmp.resolve()
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            for member in zf.infolist():
                target = (tmp / member.filename).resolve()
                if root not in target.parents and target != root:
                    raise ValueError(f"zip entry escapes destination: {member.filename}")
                zf.extract(member, tmp)
        children = [p for p in tmp.iterdir()]
        if len(children) == 1 and children[0].is_dir():
            inner = children[0]
            for item in inner.iterdir():
                shutil.move(str(item), str(tmp / item.name))
            inner.rmdir()
        if not any(
            p.is_file() and p.name.lower() == expected_filename.lower() for p in tmp.rglob("*")
        ):
            raise ValueError(f"{expected_filename} not found in archive")
        if dest.exists():
            backup = Path(tempfile.mkdtemp(prefix=f".{dest.name}.backup.", dir=dest.parent))
            backup.rmdir()
            dest.rename(backup)
        try:
            tmp.rename(dest)
        except OSError:
            if backup is not None and not dest.exists():
                backup.rename(dest)
            raise
        if backup is not None:
            symlink.rmtree(backup)
    finally:
        if tmp.exists():
            symlink.rmtree(tmp)


def _fetch(source: Source, etag: str | None) -> tuple[int, bytes, str | None, str]:
    """Returns (status, body, etag, branch_used). Retries the other branch on 404."""
    branches = [source.branch, "master" if source.branch == "main" else "main"]
    for branch in branches:
        url = f"https://github.com/{source.repo}/archive/refs/heads/{branch}.zip"
        headers = {"If-None-Match": etag} if etag and branch == source.branch else {}
        with requests.Session() as s:
            resp = s.get(url, headers=headers, timeout=_TIMEOUT, allow_redirects=True)
        if resp.status_code == 404:
            continue
        return resp.status_code, resp.content, resp.headers.get("ETag"), branch
    return 404, b"", None, source.branch


def sync_one(settings: Settings, name: str, force: bool = False) -> dict[str, Any]:
    source = SOURCES[name]
    meta = _read_meta(settings, name)
    etag = None if force else meta.get("etag")
    try:
        status, body, new_etag, branch = _fetch(source, etag)
    except requests.RequestException as exc:
        return {"source": name, "status": "error", "error": str(exc), "url": source.zip_url}
    if status == 304:
        return {"source": name, "status": "unchanged", "synced_at": meta.get("synced_at")}
    if status != 200:
        return {"source": name, "status": "error", "error": f"HTTP {status}", "url": source.zip_url}
    try:
        _extract_swap(body, _dir(settings, name), source.filename)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        return {"source": name, "status": "error", "error": f"extract failed: {exc}"}
    synced_at = datetime.now(UTC).isoformat(timespec="seconds")
    _write_meta(settings, name, {"etag": new_etag, "synced_at": synced_at, "branch": branch})
    located = locate(settings, name)
    out: dict[str, Any] = {"source": name, "status": "updated", "synced_at": synced_at}
    if located is None:
        out["warning"] = f"{source.filename} not found in the archive"
    if branch != source.branch:
        out["warning"] = f"upstream branch is now '{branch}', not '{source.branch}'"
    return out


def seed_user_rules(settings: Settings) -> Path:
    p = settings.db_dir / "userRules.json"
    if not p.is_file():
        settings.db_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_USER_RULES_SEED, indent=2), encoding="utf-8")
    return p


def sync(settings: Settings, sources: list[str] | None, force: bool) -> dict[str, Any]:
    names = sources or [n for n, s in SOURCES.items() if not s.optional]
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        return {"error": f"Unknown sources {unknown}.", "hint": f"Known: {list(SOURCES)}."}
    results = [sync_one(settings, n, force) for n in names]
    seed_user_rules(settings)
    return {"results": results, "db_dir": str(settings.db_dir), "status": status(settings)}


def status(settings: Settings) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in SOURCES:
        meta = _read_meta(settings, name)
        located = locate(settings, name)
        out[name] = {"present": located is not None, "synced_at": meta.get("synced_at")}
    return out


# --- readers (in-process cache keyed on file mtime) --------------------------------------

_cache_lock = threading.RLock()
_cache: dict[tuple[str, int, int], Any] = {}
_MAX_READER_CACHE_ENTRIES = 32


def _cached(path: Path, loader: Any) -> Any:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        if key not in _cache:
            _cache[key] = loader(path)
            if len(_cache) > _MAX_READER_CACHE_ENTRIES:
                # Keep the cache bounded without evicting unrelated current readers on every load.
                del _cache[next(iter(_cache))]
        return _cache[key]


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return [str(x) for x in v if x is not None]


@dataclass
class SteamEntry:
    pfid: str
    package_id: str | None
    name: str | None
    unpublished: bool
    url: str | None
    game_versions: list[str]
    blacklist_comment: str | None
    dependencies: dict[str, str | None]  # child pfid -> name
    is_dlc: bool


@dataclass
class SteamDB:
    by_pfid: dict[str, SteamEntry] = field(default_factory=dict)
    pfid_by_package_id: dict[str, str] = field(default_factory=dict)
    version: int = 0

    def name_for(self, package_id: str) -> str | None:
        pfid = self.pfid_by_package_id.get(package_id.lower())
        e = self.by_pfid.get(pfid) if pfid else None
        return e.name if e else None


def _load_steam_db(path: Path) -> SteamDB:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    db = SteamDB(version=int(raw.get("version") or 0))
    for key, entry in (raw.get("database") or {}).items():
        if not isinstance(entry, dict):
            continue
        pfid = str(key).lower()
        pid = entry.get("packageId") or entry.get("packageid")
        pid = str(pid).lower() if pid else None
        bl = entry.get("blacklist")
        bl_comment = None
        if isinstance(bl, dict) and bl.get("value"):
            bl_comment = str(bl.get("comment") or "community blacklisted")
        deps: dict[str, str | None] = {}
        for cp, meta in (entry.get("dependencies") or {}).items():
            if isinstance(meta, dict):
                deps[str(cp)] = meta.get("name")
            elif isinstance(meta, list) and meta:
                deps[str(cp)] = str(meta[0])
            else:
                deps[str(cp)] = None
        e = SteamEntry(
            pfid=pfid,
            package_id=pid,
            name=entry.get("steamName") or entry.get("name"),
            unpublished=bool(entry.get("unpublished")),
            url=entry.get("url"),
            game_versions=_as_list(entry.get("gameVersions")),
            blacklist_comment=bl_comment,
            dependencies=deps,
            is_dlc=bool(entry.get("appid")),
        )
        db.by_pfid[pfid] = e
        if pid and pid not in db.pfid_by_package_id:
            db.pfid_by_package_id[pid] = pfid
    return db


def steam_db(settings: Settings) -> SteamDB | None:
    p = locate(settings, "steam_db")
    return _cached(p, _load_steam_db) if p else None


@dataclass
class Rule:
    load_after: set[str] = field(default_factory=set)
    load_before: set[str] = field(default_factory=set)
    load_top: bool = False
    load_bottom: bool = False
    comments: dict[str, str] = field(default_factory=dict)
    # Our extension to the rules schema (userRules.json only in practice): drop an edge that a
    # lower layer added. RimSort's union merge has no way to remove a rule, only add one.
    remove_after: set[str] = field(default_factory=set)
    remove_before: set[str] = field(default_factory=set)


def _load_rules(path: Path) -> dict[str, Rule]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    out: dict[str, Rule] = {}
    for pid, spec in (raw.get("rules") or {}).items():
        if not isinstance(spec, dict):
            continue
        r = Rule()
        for key, target in (("loadAfter", r.load_after), ("loadBefore", r.load_before)):
            for other, meta in (spec.get(key) or {}).items():
                other_l = str(other).lower()
                target.add(other_l)
                if isinstance(meta, dict) and meta.get("comment"):
                    c = meta["comment"]
                    r.comments[other_l] = " ".join(c) if isinstance(c, list) else str(c)
        for key, attr in (("loadTop", "load_top"), ("loadBottom", "load_bottom")):
            v = spec.get(key)
            setattr(r, attr, bool(v.get("value")) if isinstance(v, dict) else bool(v))
        for key, target in (
            ("removeLoadAfter", r.remove_after),
            ("removeLoadBefore", r.remove_before),
        ):
            target.update(str(o).lower() for o in (spec.get(key) or {}))
        out[str(pid).lower()] = r
    return out


def community_rules(settings: Settings) -> dict[str, Rule] | None:
    p = locate(settings, "community_rules")
    return _cached(p, _load_rules) if p else None


def user_rules(settings: Settings) -> dict[str, Rule]:
    p = seed_user_rules(settings)
    return _cached(p, _load_rules)


@dataclass
class Replacement:
    old_pfid: str
    old_name: str | None
    new_pfid: str
    new_name: str | None
    new_package_id: str | None
    new_versions: list[str]


def _load_use_this_instead(path: Path) -> dict[str, Replacement]:
    data = path.read_bytes()
    if path.suffix == ".gz" or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    raw = json.loads(data.decode("utf-8-sig"))
    rules = raw.get("rules") if isinstance(raw, dict) else raw
    out: dict[str, Replacement] = {}
    for r in rules or []:
        if not isinstance(r, dict) or not r.get("oldWorkshopId") or not r.get("newWorkshopId"):
            continue
        out[str(r["oldWorkshopId"])] = Replacement(
            old_pfid=str(r["oldWorkshopId"]),
            old_name=r.get("oldName"),
            new_pfid=str(r["newWorkshopId"]),
            new_name=r.get("newName"),
            new_package_id=(str(r["newPackageId"]).lower() if r.get("newPackageId") else None),
            new_versions=_as_list(r.get("newVersions")),
        )
    return out


def use_this_instead(settings: Settings) -> dict[str, Replacement] | None:
    # Upstream ships .json.gz; tolerate a plain .json too.
    p = locate(settings, "use_this_instead") or locate(
        settings, "use_this_instead", "replacements.json"
    )
    return _cached(p, _load_use_this_instead) if p else None


def _load_no_version_warning(path: Path) -> set[str]:
    root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    return {(li.text or "").strip().lower() for li in root.iter("li") if (li.text or "").strip()}


def no_version_warning(settings: Settings, game_mm: str | None) -> set[str] | None:
    """Load only the warning list for the installed major.minor game version."""
    root = _dir(settings, "no_version_warning")
    if not game_mm or not root.is_dir():
        return None
    candidates = sorted(p for p in root.rglob("*") if p.name.lower() == "modidstofix.xml")
    chosen = next((p for p in candidates if p.parent.name == game_mm), None)
    if chosen is None:
        return None
    return _cached(chosen, _load_no_version_warning)


def rimworld_versions(settings: Settings) -> dict[str, Any] | None:
    p = locate(settings, "rimworld_versions")
    return _cached(p, lambda q: json.loads(q.read_text(encoding="utf-8-sig"))) if p else None


def age_phrase(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    secs = max(0, int(time.time() - then.timestamp()))
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h {secs % 3600 // 60}m ago"
    return f"{secs // 86400}d ago"
