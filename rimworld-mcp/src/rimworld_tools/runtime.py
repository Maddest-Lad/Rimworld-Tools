from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from . import db, locking
from .config import Settings, load_environment


@dataclass
class Runtime:
    """Process-owned settings and preparation for operations with local side effects."""

    settings: Settings
    _mutation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _database_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def mutation(self, scope: str = "subscriptions"):
        """Serialize local side effects across tasks and MCP processes, one lock per scope.

        `subscriptions` covers Steam subscription changes; `modlist` covers ModsConfig.xml writes.
        """
        async with self._mutation_lock:
            lock = locking.WindowsFileLock(self.settings.db_dir / f".rimworld-tools-{scope}.lock")
            if not await asyncio.to_thread(lock.acquire):
                what = "Steam subscriptions" if scope == "subscriptions" else "ModsConfig.xml"
                yield {
                    "error": f"Another RimWorld Tools operation is still using {what}.",
                    "hint": "Wait for it to finish, then retry.",
                }
                return
            try:
                yield None
            finally:
                await asyncio.to_thread(lock.release)

    async def ensure_community_data(self) -> dict[str, Any] | None:
        """Refresh missing or day-old advisory data while preserving usable local copies."""
        sources = [name for name, source in db.SOURCES.items() if not source.optional]
        status = await asyncio.to_thread(db.status, self.settings)
        cutoff = datetime.now(UTC) - timedelta(days=1)

        def needs_sync() -> bool:
            for name in sources:
                entry = status[name]
                if not entry["present"] or not entry["synced_at"]:
                    return True
                try:
                    if datetime.fromisoformat(entry["synced_at"]) < cutoff:
                        return True
                except ValueError:
                    return True
            return False

        if not needs_sync():
            return None
        async with self._database_lock:
            lock = locking.WindowsFileLock(self.settings.db_dir / ".rimworld-tools-db.lock")
            if not await asyncio.to_thread(lock.acquire):
                return {"notice": "Community data is being refreshed by another MCP process."}
            try:
                result = await asyncio.to_thread(db.sync, self.settings, None, False)
            finally:
                await asyncio.to_thread(lock.release)
        failed = [row for row in result["results"] if row["status"] == "error"]
        if failed:
            return {
                "notice": "Community data refresh failed; using any existing local data.",
                "details": failed,
            }
        return None


_runtime: Runtime | None = None


def configure(settings: Settings | None = None) -> Runtime:
    """Create the process runtime explicitly at startup, or lazily for embedded use."""
    global _runtime
    if settings is None:
        load_environment()
        settings = Settings.from_env()
    _runtime = Runtime(settings)
    return _runtime


def get() -> Runtime:
    return _runtime or configure()
