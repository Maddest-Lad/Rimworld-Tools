from __future__ import annotations

import os
import shutil
import stat
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


def _on_rmtree_error(func, path, _exc_info) -> None:
    # Read-only files inside mod folders make rmtree fail with EACCES; loosen and retry once.
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    func(path)


def rmtree(path: Path) -> None:
    """shutil.rmtree that tolerates read-only files and paths past MAX_PATH."""
    shutil.rmtree(long_path(path), onexc=_on_rmtree_error)
