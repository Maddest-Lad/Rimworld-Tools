from __future__ import annotations

import logging
from typing import Any, Self

import pytest
import requests

from src.rimworld_tools import webapi
from src.rimworld_tools.cache import Cache

KEY = "0123456789ABCDEF0123456789ABCDEF"


def _details(pfid: str, result: int = 1, **extra: Any) -> dict[str, Any]:
    base = {
        "publishedfileid": pfid,
        "result": result,
        "title": f"Mod {pfid}",
        "time_updated": 1700000000,
        "file_size": "1234",
        "tags": [{"tag": "1.5"}, {"tag": "Mod"}],
    }
    base.update(extra)
    return base


class FakePoster:
    """Stands in for _post_with_retry; scripted per call."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, data: dict[str, Any], key: str | None = None) -> dict[str, Any]:
        self.calls.append(data)
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class TestFileDetails:
    def test_description_is_opt_in_without_mutating_cache(self, tmp_path, monkeypatch):
        fake = FakePoster(
            [
                {
                    "response": {
                        "publishedfiledetails": [
                            _details("1", description="[b]Full description[/b]")
                        ]
                    }
                }
            ]
        )
        monkeypatch.setattr(webapi, "_post_with_retry", fake)
        cache = Cache(tmp_path)
        assert "description" not in webapi.file_details(["1"], cache=cache).items["1"]
        rich = webapi.file_details(["1"], cache=cache, include_description=True)
        assert rich.items["1"]["description"] == "[b]Full description[/b]"
        assert "description" not in webapi.file_details(["1"], cache=cache).items["1"]
        assert cache.lookup("file_details", ["1"]).hits["1"]["description"]
        assert len(fake.calls) == 1

    def test_description_refetches_legacy_cache(self, tmp_path, monkeypatch):
        cache = Cache(tmp_path)
        cache.store("file_details", {"1": webapi._normalise(_details("1"))})
        fake = FakePoster(
            [
                {
                    "response": {
                        "publishedfiledetails": [
                            _details("1", description="New"),
                            _details("2", result=9),
                        ]
                    }
                }
            ]
        )
        monkeypatch.setattr(webapi, "_post_with_retry", fake)
        result = webapi.file_details(["1", "2"], cache=cache, include_description=True)
        assert result.items["1"]["description"] == "New"
        assert result.items["2"]["description"] is None
        assert not result.cache.hits

    def test_unpublished_is_result_not_equal_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakePoster(
            [{"response": {"publishedfiledetails": [_details("1"), _details("2", result=9)]}}]
        )
        monkeypatch.setattr(webapi, "_post_with_retry", fake)
        res = webapi.file_details(["1", "2"])
        assert res.items["1"]["unpublished"] is False
        assert res.items["2"]["unpublished"] is True
        assert res.items["1"]["tags"] == ["1.5", "Mod"]
        assert res.items["1"]["file_size"] == 1234
        assert fake.calls[0]["itemcount"] == 2
        assert fake.calls[0]["publishedfileids[1]"] == "2"

    def test_chunks_at_300_and_survives_bad_chunk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ids = [str(i) for i in range(1, 302)]
        fake = FakePoster(
            [
                {"response": {"publishedfiledetails": [_details(p) for p in ids[:300]]}},
                requests.RequestException("boom"),
            ]
        )
        monkeypatch.setattr(webapi, "_post_with_retry", fake)
        res = webapi.file_details(ids)
        assert len(fake.calls) == 2
        assert len(res.items) == 300
        assert res.failed_ids == ["301"]
        assert len(res.errors) == 1

    def test_missing_entries_are_reported_failed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakePoster([{"response": {"publishedfiledetails": [_details("1")]}}])
        monkeypatch.setattr(webapi, "_post_with_retry", fake)
        res = webapi.file_details(["1", "2"])
        assert res.failed_ids == ["2"]


class TestCollection:
    def test_filters_to_mods_only_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakePoster(
            [
                {
                    "response": {
                        "CollectionDetails": [
                            {
                                "Result": 1,
                                "Children": [
                                    {"PublishedFileId": "10", "FileType": 0},
                                    {"publishedfileid": "11", "filetype": 2},
                                    {"publishedfileid": "12", "filetype": 0},
                                ],
                            }
                        ]
                    }
                }
            ]
        )
        monkeypatch.setattr(webapi, "_post_with_retry", fake)
        assert webapi.collection_children("5") == (["10", "12"], None)

    def test_non_collection_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakePoster([{"response": {"collectiondetails": [{"result": 9}]}}])
        monkeypatch.setattr(webapi, "_post_with_retry", fake)
        assert webapi.collection_children("5") == (None, None)


class TestUrlParsing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2009463077", "2009463077"),
            ("https://steamcommunity.com/sharedfiles/filedetails/?id=2009463077", "2009463077"),
            ("https://steamcommunity.com/workshop/filedetails/?id=123&searchtext=x", "123"),
            ("steamcommunity.com/sharedfiles/filedetails/?l=english&id=42", "42"),
            ("not a url", None),
        ],
    )
    def test_parse(self, raw: str, expected: str | None) -> None:
        assert webapi.parse_workshop_url(raw) == expected


class TestKeyHygiene:
    def test_redact_strips_key_and_query_param(self) -> None:
        text = f"GET https://x/?appid=1&key={KEY}&q=2 failed; key was {KEY}"
        out = webapi.redact(text, KEY)
        assert KEY not in out
        assert "key=***" in out

    def test_search_never_leaks_key_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Resp:
            status_code = 500
            text = ""

            def raise_for_status(self) -> None:
                raise requests.HTTPError(f"500 for url ...?key={KEY}")

        class Sess:
            def __enter__(self) -> Self:
                return self

            def __exit__(self, *a: object) -> None:
                pass

            def get(self, *a: object, **k: object) -> Resp:
                return Resp()

        monkeypatch.setattr(webapi.requests, "Session", Sess)
        with pytest.raises(requests.HTTPError) as ei:
            webapi.search("x", KEY)
        # The raw exception carries the key; workshop.search redacts before returning.
        assert KEY in str(ei.value)
        assert KEY not in webapi.redact(str(ei.value), KEY)

    def test_urllib3_logger_is_quiet(self) -> None:
        assert logging.getLogger("urllib3").level >= logging.WARNING


class TestRetry:
    def test_retries_transient_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        codes = iter([503, 200])

        class Resp:
            def __init__(self, code: int) -> None:
                self.status_code = code

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, str]:
                return {"ok": "yes"}

        class Sess:
            def __enter__(self) -> Self:
                return self

            def __exit__(self, *a: object) -> None:
                pass

            def post(self, *a: object, **k: object) -> Resp:
                return Resp(next(codes))

        monkeypatch.setattr(webapi.requests, "Session", Sess)
        monkeypatch.setattr(webapi.time, "sleep", lambda _: None)
        assert webapi._post_with_retry("u", {}) == {"ok": "yes"}

    def test_non_retryable_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = 0

        class Resp:
            status_code = 404

            def raise_for_status(self) -> None:
                raise requests.HTTPError("404")

        class Sess:
            def __enter__(self) -> Self:
                return self

            def __exit__(self, *a: object) -> None:
                pass

            def post(self, *a: object, **k: object) -> Resp:
                nonlocal calls
                calls += 1
                return Resp()

        monkeypatch.setattr(webapi.requests, "Session", Sess)
        with pytest.raises(requests.HTTPError):
            webapi._post_with_retry("u", {})
        assert calls == 1
