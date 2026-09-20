from __future__ import annotations

import logging
import re
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path

import vdf

from .config import RIMWORLD_APP_ID, Settings

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^\d+\.\d+")

_EXECUTABLES = ("RimWorldWin64.exe", "RimWorldWin.exe")


@dataclass(frozen=True)
class Found:
    """A resolved path plus how it was found, so callers can tell a hit from a guess."""

    path: str
    provenance: str


@dataclass(frozen=True)
class RimWorldPaths:
    game_dir: Found | None = None
    mods_dir: Found | None = None
    config_dir: Found | None = None
    workshop_dir: Found | None = None
    steam_root: Found | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {k: (asdict(v) if isinstance(v, Found) else v) for k, v in asdict(self).items()}


def read_version(game_dir: Path) -> str | None:
    """First line of Version.txt, e.g. '1.6.4871 rev573'. None if absent or malformed."""
    try:
        first = (game_dir / "Version.txt").read_text(encoding="utf-8-sig").splitlines()[0].strip()
    except (OSError, IndexError, UnicodeDecodeError):
        return None
    return first if _VERSION_RE.match(first) else None


def is_rimworld_dir(candidate: Path) -> bool:
    """Content-validate a candidate. Never trust a directory by its name alone."""
    try:
        if not candidate.is_dir():
            return False
    except OSError:
        return False
    if read_version(candidate) is not None:
        return True
    return any((candidate / exe).exists() for exe in _EXECUTABLES)


def _read_registry(key_path: str, value: str) -> str | None:
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key_path) as key:
                data, _ = winreg.QueryValueEx(key, value)
                if data:
                    return str(data)
        except OSError:
            continue
    return None


def _is_steam_root(path: Path) -> bool:
    return (path / "steamapps").is_dir() or (path / "config" / "libraryfolders.vdf").is_file()


def find_steam_root() -> Found | None:
    for key in (r"SOFTWARE\Wow6432Node\Valve\Steam", r"SOFTWARE\Valve\Steam"):
        raw = _read_registry(key, "InstallPath")
        if raw and _is_steam_root(Path(raw)):
            return Found(str(Path(raw)), f"Steam registry ({key})")
    return None


def _load_libraryfolders(steam_root: Path) -> dict | None:
    for rel in ("config/libraryfolders.vdf", "steamapps/libraryfolders.vdf"):
        manifest = steam_root / rel
        if not manifest.is_file():
            continue
        try:
            parsed = vdf.loads(manifest.read_text(encoding="utf-8-sig"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            logger.warning("could not parse %s: %s", manifest, exc)
            continue
        # Top-level key casing is inconsistent across Steam versions.
        folders = next((v for k, v in parsed.items() if k.lower() == "libraryfolders"), None)
        if isinstance(folders, dict):
            return folders
    return None


def _library_paths(steam_root: Path) -> list[Path]:
    """Every Steam library root, from libraryfolders.vdf. Always includes steam_root itself."""
    roots = [steam_root]
    folders = _load_libraryfolders(steam_root)
    if folders:
        for entry in folders.values():
            if isinstance(entry, dict) and entry.get("path"):
                roots.append(Path(str(entry["path"])))
    return roots


def _library_declares_rimworld(steam_root: Path, library: Path) -> bool:
    """True if libraryfolders.vdf lists AppID 294100 under this library."""
    folders = _load_libraryfolders(steam_root)
    if not folders:
        return False
    for entry in folders.values():
        if not isinstance(entry, dict):
            continue
        if Path(str(entry.get("path", ""))) != library:
            continue
        apps = entry.get("apps")
        if isinstance(apps, dict) and str(RIMWORLD_APP_ID) in apps:
            return True
    return False


def find_rimworld_in_steam(steam_root: Path) -> Found | None:
    for library in _library_paths(steam_root):
        candidate = library / "steamapps" / "common" / "RimWorld"
        if not is_rimworld_dir(candidate):
            continue
        if _library_declares_rimworld(steam_root, library):
            return Found(str(candidate), f"Steam libraryfolders.vdf (AppID {RIMWORLD_APP_ID})")
        return Found(str(candidate), "Steam library layout")
    return None


def find_config_dir() -> Found | None:
    home = Path.home()
    candidate = home / "AppData/LocalLow/Ludeon Studios/RimWorld by Ludeon Studios/Config"
    if (candidate / "ModsConfig.xml").is_file():
        return Found(str(candidate), "Windows LocalLow (ModsConfig.xml present)")
    return None


def _workshop_dir_for(game_dir: Path) -> Found | None:
    """Workshop content sits beside `common`, so truncate the game path at that segment."""
    parts = game_dir.parts
    if "common" not in parts:
        return None
    steamapps = Path(*parts[: parts.index("common")])
    candidate = steamapps / "workshop" / "content" / str(RIMWORLD_APP_ID)
    if candidate.is_dir():
        return Found(str(candidate), "derived from game path")
    return None


def discover(settings: Settings | None = None) -> RimWorldPaths:
    """Run the Windows/Steam discovery pipeline. Every path is content-validated."""
    settings = settings or Settings.from_env()

    steam = find_steam_root()
    game = find_rimworld_in_steam(Path(steam.path)) if steam else None
    game_dir = Path(game.path) if game else None

    if settings.mods_dir is not None:
        mods = Found(str(settings.mods_dir), "RIMWORLD_TOOLS_MODS_DIR")
    elif game_dir is not None and (game_dir / "Mods").is_dir():
        mods = Found(str(game_dir / "Mods"), "derived from game path")
    else:
        mods = None

    return RimWorldPaths(
        game_dir=game,
        mods_dir=mods,
        config_dir=find_config_dir(),
        workshop_dir=_workshop_dir_for(game_dir) if game_dir else None,
        steam_root=steam,
        version=read_version(game_dir) if game_dir else None,
    )
