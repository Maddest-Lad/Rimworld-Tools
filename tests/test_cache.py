from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
import requests

from src.rimworld_tools import cache, webapi


def _details(pfid: str, result: int = 1) -> dict[str, Any]:
    return {"publishedfileid": pfid, "result": result, "title": f"Mod {pfid}", "time_updated": 1}


class CountingPoster:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail_next = False

    def __call__(self, url: str, data: dict[str, Any], key: str | None = None) -> dict[str, Any]:
        ids = [v for k, v in data.items() if k.startswith("publishedfileids")]
        self.calls.append(ids)
        if self.fail_next:
            self.fail_next = False
            raise requests.RequestException("boom")
        if "Collection" in url:
            return {
                "response": {
                    "collectiondetails": [
                        {"result": 1, "children": [{"publishedfileid": "9", "filetype": 0}]}
                    ]
                }
            }
        return {
            "response": {"publishedfiledetails": [_details(i, 9 if i == "77" else 1) for i in ids]}
        }


@pytest.fixture
def poster(monkeypatch: pytest.MonkeyPatch) -> CountingPoster:
    p = CountingPoster()
    monkeypatch.setattr(webapi, "_post_with_retry", p)
    return p


class TestFileDetailsCache:
    def test_second_call_is_served_from_cache(self, tmp_path: Path, poster: CountingPoster) -> None:
        c = cache.Cache(tmp_path)
        first = webapi.file_details(["1", "2"], cache=c)
        assert first.cache_summary() is None
        assert len(poster.calls) == 1
        second = webapi.file_details(["1", "2"], cache=c)
        assert len(poster.calls) == 1  # no HTTP
        assert second.items == first.items
        summary = second.cache_summary()
        assert summary is not None
        assert summary["hits"] == ["1", "2"] and summary["fetched_live"] == []
        assert summary["note"].startswith("all 2 from cache, oldest fetched")
        assert "refresh=true" in summary["note"]
        assert summary["oldest_cached_at"].endswith("+00:00")

    def test_partial_hit_fetches_only_misses(self, tmp_path: Path, poster: CountingPoster) -> None:
        c = cache.Cache(tmp_path)
        webapi.file_details(["1", "2"], cache=c)
        res = webapi.file_details(["2", "3", "4"], cache=c)
        assert poster.calls[-1] == ["3", "4"]
        assert set(res.items) == {"2", "3", "4"}
        s = res.cache_summary()
        assert s is not None and s["hits"] == ["2"] and s["fetched_live"] == ["3", "4"]
        assert s["note"].startswith("1 of 3 from cache")

    def test_refresh_bypasses_and_overwrites(self, tmp_path: Path, poster: CountingPoster) -> None:
        c = cache.Cache(tmp_path)
        webapi.file_details(["1"], cache=c)
        res = webapi.file_details(["1"], cache=c, refresh=True)
        assert len(poster.calls) == 2 and res.cache_summary() is None
        assert webapi.file_details(["1"], cache=c).cache_summary() is not None

    def test_expired_entry_refetches(
        self, tmp_path: Path, poster: CountingPoster, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = cache.Cache(tmp_path)
        webapi.file_details(["1"], cache=c)
        now = time.time()
        monkeypatch.setattr(cache.time, "time", lambda: now + cache.TTL_FILE_DETAILS + 1)
        webapi.file_details(["1"], cache=c)
        assert len(poster.calls) == 2

    def test_unpublished_has_shorter_ttl(
        self, tmp_path: Path, poster: CountingPoster, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = cache.Cache(tmp_path)
        webapi.file_details(["77", "1"], cache=c)
        now = time.time()
        monkeypatch.setattr(cache.time, "time", lambda: now + cache.TTL_UNPUBLISHED + 1)
        webapi.file_details(["77", "1"], cache=c)
        assert poster.calls[-1] == ["77"]  # unpublished expired, the other did not

    def test_failures_are_never_cached(self, tmp_path: Path, poster: CountingPoster) -> None:
        c = cache.Cache(tmp_path)
        poster.fail_next = True
        res = webapi.file_details(["1"], cache=c)
        assert res.failed_ids == ["1"]
        assert c.stats()["entries"] == 0
        webapi.file_details(["1"], cache=c)
        assert len(poster.calls) == 2

    def test_persists_across_instances(self, tmp_path: Path, poster: CountingPoster) -> None:
        webapi.file_details(["1"], cache=cache.Cache(tmp_path))
        res = webapi.file_details(["1"], cache=cache.Cache(tmp_path))
        assert len(poster.calls) == 1 and res.cache_summary() is not None


class TestCollectionAndSearchCache:
    def test_collection_cached_with_timestamp(self, tmp_path: Path, poster: CountingPoster) -> None:
        c = cache.Cache(tmp_path)
        ids, at = webapi.collection_children("5", cache=c)
        assert ids == ["9"] and at is None
        ids2, at2 = webapi.collection_children("5", cache=c)
        assert ids2 == ["9"] and at2 is not None and len(poster.calls) == 1
        assert webapi.collection_children("5", cache=c, refresh=True)[1] is None

    def test_search_cache_keyed_on_all_params(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = cache.Cache(tmp_path)
        calls = 0

        class Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return {"response": {"total": 1, "publishedfiledetails": [_details("1")]}}

        class Sess:
            def __enter__(self):
                return self

            def __exit__(self, *a: object) -> None:
                pass

            def get(self, *a: object, **k: object) -> Resp:
                nonlocal calls
                calls += 1
                return Resp()

        monkeypatch.setattr(webapi.requests, "Session", Sess)
        first = webapi.search("x", "k", 5, ["Mod"], [], "relevance", 90, cache=c)
        assert "cache" not in first
        second = webapi.search("x", "k", 5, ["Mod"], [], "relevance", 90, cache=c)
        assert calls == 1 and second["cache"]["note"].startswith("fetched")
        webapi.search(
            "x", "k", 5, ["Mod", "1.6"], [], "relevance", 90, cache=c
        )  # different filters
        assert calls == 2


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
