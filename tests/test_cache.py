from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.rimworld_tools import cache


class TestCacheStore:
    def test_busy_disk_lock_does_not_overwrite_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cache.WindowsFileLock, "acquire", lambda *_: False)
        current = cache.Cache(tmp_path)
        current.store("file_details", {"1": {"a": 1}})
        assert current.stats()["entries"] == 0
        assert current.clear() == {"error": "Cache is being updated by another MCP process."}

    def test_instances_share_in_process_state(self, tmp_path: Path) -> None:
        first = cache.Cache(tmp_path)
        second = cache.Cache(tmp_path)
        first.store("file_details", {"1": {"value": "first"}})
        second.store("file_details", {"2": {"value": "second"}})
        assert set(first.lookup("file_details", ["1", "2"]).hits) == {"1", "2"}
        first.clear()
        assert second.lookup("file_details", ["1", "2"]).misses == ["1", "2"]

    def test_clear_and_stats(self, tmp_path: Path) -> None:
        c = cache.Cache(tmp_path)
        c.store("file_details", {"1": {"a": 1}, "2": {"b": 2}})
        c.store("search", {"h": {"q": 1}})
        st = c.stats()
        assert st["entries"] == 3 and st["bytes"] > 0
        out = c.clear()
        assert out["cleared_entries"] == 3
        assert c.stats()["entries"] == 0 and c.lookup("file_details", ["1"]).misses == ["1"]

    def test_describe_phrases(self) -> None:
        now = time.time()
        assert cache.describe(now - 30).startswith("fetched 30s ago (")
        assert cache.describe(now - 5 * 60).startswith("fetched 5m ago")
        assert cache.describe(now - 2 * 3600 - 14 * 60).startswith("fetched 2h 14m ago")
        assert cache.describe(now - 3 * 86400 - 3600).startswith("fetched 3d 1h ago")
