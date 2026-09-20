from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from . import steamcmd
from .config import Settings


@dataclass
class Runtime:
    """Process-owned settings and preparation for operations with local side effects."""

    settings: Settings
    _download_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def ensure_download_environment(self) -> dict[str, Any] | None:
        """Install SteamCMD and verify its Mods junction once before a download operation."""
        async with self._download_lock:
            state = await steamcmd.setup(self.settings)
        if state.get("error"):
            return state
        if state.get("installed") and state.get("junction_ok"):
            return None
        return {
            "error": "SteamCMD environment is not ready for downloads.",
            "hint": "Check environment_status() for the junction and Mods folder state.",
            "status": state,
        }


_runtime: Runtime | None = None


def configure(settings: Settings | None = None) -> Runtime:
    """Create the process runtime explicitly at startup, or lazily for embedded use."""
    global _runtime
    _runtime = Runtime(settings or Settings.from_env())
    return _runtime


def get() -> Runtime:
    return _runtime or configure()
