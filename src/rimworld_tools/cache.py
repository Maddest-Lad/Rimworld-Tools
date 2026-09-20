from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HOUR = 3600
# TTLs matched to how fast the data actually changes, not to how often tools get called.
TTL_FILE_DETAILS = 6 * HOUR
TTL_UNPUBLISHED = 1 * HOUR  # private mods get republished; re-check sooner
TTL_COLLECTION = 24 * HOUR
TTL_SEARCH = 1 * HOUR


def ttl_for(namespace: str, data: Any) -> int:
    if namespace == "file_details":
        return (
            TTL_UNPUBLISHED
            if isinstance(data, dict) and data.get("unpublished")
            else TTL_FILE_DETAILS
        )
    if namespace == "collection":
        return TTL_COLLECTION
    return TTL_SEARCH


def key_for(*parts: Any) -> str:
    """Stable key for a search/query: hash of the JSON-encoded parameters."""
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def describe(cached_at: float) -> str:
    """LLM-readable: 'fetched 2h 14m ago (2026-09-19 13:41 UTC)'."""
    secs = max(0, int(time.time() - cached_at))
    if secs < 60:
        age = f"{secs}s ago"
    elif secs < HOUR:
        age = f"{secs // 60}m ago"
    elif secs < 24 * HOUR:
        age = f"{secs // HOUR}h {secs % HOUR // 60}m ago"
    else:
        age = f"{secs // (24 * HOUR)}d {secs % (24 * HOUR) // HOUR}h ago"
    stamp = datetime.fromtimestamp(cached_at, UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"fetched {age} ({stamp})"


def iso(cached_at: float) -> str:
    return datetime.fromtimestamp(cached_at, UTC).isoformat(timespec="seconds")


@dataclass
class Lookup:
    hits: dict[str, Any] = field(default_factory=dict)
    cached_at: dict[str, float] = field(default_factory=dict)
    misses: list[str] = field(default_factory=list)

    def summary(self, total: int) -> dict[str, Any] | None:
        """Top-level `cache` block for a tool response. None when nothing came from cache."""
        if not self.cached_at:
            return None
        oldest = min(self.cached_at.values())
        n = len(self.cached_at)
        note = f"{n} of {total} from cache, oldest {describe(oldest)}"
        if n == total:
            note = f"all {total} from cache, oldest {describe(oldest)}"
        return {
            "hits": sorted(self.cached_at),
            "fetched_live": self.misses,
            "oldest_cached_at": iso(oldest),
            "note": note + ". Pass refresh=true to refetch.",
        }


class Cache:
    """On-disk JSON cache: `<root>/<namespace>.json` = {key: {"at": epoch, "data": ...}}."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()
        self._loaded: dict[str, dict[str, Any]] = {}

    def _path(self, namespace: str) -> Path:
        return self.root / f"{namespace}.json"

    def _load(self, namespace: str) -> dict[str, Any]:
        if namespace not in self._loaded:
            try:
                self._loaded[namespace] = json.loads(self._path(namespace).read_text("utf-8"))
            except (OSError, ValueError):
                self._loaded[namespace] = {}
        return self._loaded[namespace]

    def _save(self, namespace: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._path(namespace).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._loaded[namespace], separators=(",", ":")), "utf-8")
        tmp.replace(self._path(namespace))

    def lookup(
        self,
        namespace: str,
        keys: Iterable[str],
        refresh: bool = False,
        ttl: Callable[[Any], int] | None = None,
    ) -> Lookup:
        out = Lookup()
        keys = list(keys)
        if refresh:
            out.misses = keys
            return out
        now = time.time()
        with self._lock:
            store = self._load(namespace)
            for k in keys:
                entry = store.get(k)
                if not entry:
                    out.misses.append(k)
                    continue
                max_age = ttl(entry["data"]) if ttl else ttl_for(namespace, entry["data"])
                if now - entry["at"] > max_age:
                    out.misses.append(k)
                    continue
                out.hits[k] = entry["data"]
                out.cached_at[k] = entry["at"]
        return out

    def store(self, namespace: str, items: dict[str, Any]) -> None:
        """Only successes are ever passed here; failures are never cached."""
        if not items:
            return
        now = time.time()
        with self._lock:
            store = self._load(namespace)
            for k, v in items.items():
                store[k] = {"at": now, "data": v}
            self._save(namespace)

    def clear(self) -> dict[str, Any]:
        with self._lock:
            stats = self.stats()
            for f in self.root.glob("*.json"):
                f.unlink()
            self._loaded.clear()
        return {"cleared_entries": stats["entries"], "freed_bytes": stats["bytes"]}

    def stats(self) -> dict[str, Any]:
        entries = 0
        size = 0
        if self.root.is_dir():
            for f in self.root.glob("*.json"):
                size += f.stat().st_size
                try:
                    entries += len(json.loads(f.read_text("utf-8")))
                except (OSError, ValueError):
                    continue
        return {"entries": entries, "bytes": size, "dir": str(self.root)}
