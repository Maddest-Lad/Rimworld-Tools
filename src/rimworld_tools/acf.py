from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

import psutil
import vdf

from .config import RIMWORLD_APP_ID

logger = logging.getLogger(__name__)

_INSTALLED = "WorkshopItemsInstalled"
_DETAILS = "WorkshopItemDetails"
_STEAM_PROCESSES = {"steamcmd.exe", "steam.exe"}


@dataclass(frozen=True)
class AcfItem:
    pfid: str
    timeupdated: int | None
    manifest: str | None
    size: int | None


def _to_int(raw: object) -> int | None:
    # Every ACF value is a string, including timestamps; garbage must yield None, not raise.
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def empty() -> dict:
    return {
        "AppWorkshop": {
            "appid": str(RIMWORLD_APP_ID),
            "SizeOnDisk": "0",
            _INSTALLED: {},
            _DETAILS: {},
        }
    }


def load(path: Path) -> dict:
    """Parse an appworkshop ACF. A missing file yields an empty skeleton."""
    if not path.is_file():
        return empty()
    return vdf.loads(path.read_bytes().decode("utf-8", errors="replace"))


def root(data: dict) -> dict:
    node = next((v for k, v in data.items() if k.lower() == "appworkshop"), None)
    if not isinstance(node, dict):
        node = data.setdefault("AppWorkshop", {})
    node.setdefault(_INSTALLED, {})
    node.setdefault(_DETAILS, {})
    return node


def items(data: dict) -> dict[str, AcfItem]:
    """Merge both sections into one view keyed by pfid. Installed entries win on conflict."""
    node = root(data)
    merged: dict[str, AcfItem] = {}
    for pfid, entry in node[_DETAILS].items():
        if isinstance(entry, dict):
            merged[str(pfid)] = AcfItem(
                pfid=str(pfid),
                timeupdated=_to_int(entry.get("timeupdated")),
                manifest=str(entry["manifest"]) if entry.get("manifest") else None,
                size=None,
            )
    for pfid, entry in node[_INSTALLED].items():
        if isinstance(entry, dict):
            merged[str(pfid)] = AcfItem(
                pfid=str(pfid),
                timeupdated=_to_int(entry.get("timeupdated")),
                manifest=str(entry["manifest"]) if entry.get("manifest") else None,
                size=_to_int(entry.get("size")),
            )
    return merged


def remove_items(data: dict, pfids: list[str]) -> dict[str, set[str]]:
    """Drop pfids from BOTH sections. Returns the manifest ids each one referenced.

    Leaving a stale entry behind is the classic bug: SteamCMD then believes the item is
    installed, reports success on the next download, and writes nothing.
    """
    node = root(data)
    manifests: dict[str, set[str]] = {}
    for pfid in pfids:
        found: set[str] = set()
        for section in (_INSTALLED, _DETAILS):
            entry = node[section].pop(str(pfid), None)
            if isinstance(entry, dict) and entry.get("manifest"):
                found.add(str(entry["manifest"]))
        manifests[str(pfid)] = found
    return manifests


def orphans(data: dict, content_dir: Path) -> list[str]:
    """Pfids recorded in either section that have no directory on disk."""
    on_disk: set[str] = set()
    if content_dir.is_dir():
        on_disk = {p.name for p in content_dir.iterdir() if p.is_dir() and p.name.isdigit()}
    node = root(data)
    recorded = set(map(str, node[_INSTALLED])) | set(map(str, node[_DETAILS]))
    return sorted(recorded - on_disk, key=int)


def steam_processes_running() -> list[str]:
    """Names of running Steam/SteamCMD processes. Both rewrite the ACF on exit."""
    running: list[str] = []
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in _STEAM_PROCESSES:
            running.append(name)
    return sorted(set(running))


def repair(path: Path, content_dir: Path, dry_run: bool = True) -> dict:
    """Remove ACF entries whose item directory no longer exists."""
    if not path.is_file():
        return {"orphans": [], "removed": False, "note": "no ACF file present"}
    data = load(path)
    found = orphans(data, content_dir)
    out: dict = {"orphans": found, "removed": False, "dry_run": dry_run}
    if dry_run or not found:
        return out
    running = steam_processes_running()
    if running:
        out["error"] = f"Refusing to write the ACF while {', '.join(running)} is running."
        out["hint"] = "Both rewrite the file on exit and would discard the repair. Close them."
        return out
    remove_items(data, found)
    backup = save(path, data)
    out["removed"] = True
    out["backup_path"] = str(backup) if backup else None
    return out


def save(path: Path, data: dict) -> Path | None:
    """Write with a .backup that is restored if the write fails. Returns the backup path.

    A truncated ACF makes Steam re-download everything, so this is never a plain overwrite.
    """
    backup: Path | None = None
    if path.is_file():
        backup = path.with_suffix(path.suffix + ".backup")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(vdf.dumps(data, pretty=True), encoding="utf-8")
    except OSError:
        if backup is not None:
            shutil.copy2(backup, path)
        raise
    return backup
