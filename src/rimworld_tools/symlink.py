from __future__ import annotations

import _winapi
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

_LONG_PREFIX = "\\\\?\\"


def long_path(path: Path) -> str:
    """Prefix with \\\\?\\ so Win32 calls accept paths past MAX_PATH (260 chars).

    Uses abspath, not resolve(): resolve() follows junctions, which would turn an
    rmtree of a link into an rmtree of the Mods folder it points at.
    """
    raw = str(path)
    if raw.startswith(_LONG_PREFIX):
        return raw
    return _LONG_PREFIX + os.path.abspath(raw)


def _strip_long_prefix(raw: str) -> str:
    return raw.removeprefix(_LONG_PREFIX)


def read_junction(path: Path) -> Path | None:
    """Target of a junction/symlink at `path`, else None. os.path.islink misses junctions."""
    try:
        return Path(_strip_long_prefix(os.readlink(path)))
    except OSError:
        return None


def _on_rmtree_error(func, path, _exc_info) -> None:
    # Read-only files inside mod folders make rmtree fail with EACCES; loosen and retry once.
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    func(path)


def rmtree(path: Path) -> None:
    """shutil.rmtree that tolerates read-only files and paths past MAX_PATH."""
    shutil.rmtree(long_path(path), onexc=_on_rmtree_error)


@dataclass(frozen=True)
class JunctionResult:
    created: bool
    already_correct: bool = False
    error: str | None = None
    hint: str | None = None


def ensure_junction(link: Path, target: Path, force: bool = False) -> JunctionResult:
    """Make `link` a junction to `target`. Never removes an obstruction unless `force`."""
    if not target.is_dir():
        return JunctionResult(
            created=False,
            error=f"Junction target does not exist or is not a directory: {target}",
            hint="Create the Mods folder first, or pass the correct RIMWORLD_TOOLS_MODS_DIR.",
        )

    existing = read_junction(link)
    if existing is not None:
        if existing.resolve() == target.resolve():
            return JunctionResult(created=False, already_correct=True)
        if not force:
            return JunctionResult(
                created=False,
                error=f"{link} is already a junction to {existing}, not {target}.",
                hint="Pass force=true to repoint it.",
            )
        os.rmdir(link)
    elif link.is_file():
        if not force:
            return JunctionResult(
                created=False,
                error=f"{link} exists and is a file.",
                hint="Pass force=true to delete it and create the junction.",
            )
        link.unlink()
    elif link.is_dir():
        if any(link.iterdir()):
            if not force:
                return JunctionResult(
                    created=False,
                    error=f"{link} is a non-empty directory; refusing to replace it.",
                    hint=(
                        "Move its contents into the Mods folder (they are likely previously "
                        "downloaded mods), then retry — or pass force=true to delete them."
                    ),
                )
            rmtree(link)
        else:
            link.rmdir()

    link.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))
    return JunctionResult(created=True)
