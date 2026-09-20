from __future__ import annotations

from unittest.mock import AsyncMock

from src.rimworld_tools import steam_transport, workshop, workshop_queries
from src.rimworld_tools.config import Settings


async def test_cache_is_account_and_description_scoped(tmp_path, monkeypatch):
    settings = Settings(None, tmp_path / "db")
    account = "1"
    calls = []

    async def request(_, action, **args):
        if action == "probe":
            return {"account": account}
        calls.append(args)
        item = {"pfid": "10", "title": "Mod"}
        if args["description"]:
            item["description"] = "Long text"
        return {"account": account, "items": [item], "failed": []}

    monkeypatch.setattr(steam_transport, "request", request)
    first = await workshop_queries.details(settings, ["10"])
    first["items"][0]["extra"] = "must not persist"
    again = await workshop_queries.details(settings, ["10"])
    assert "extra" not in again["items"][0]
    assert again["cache"]["hits"] == ["10"]
    assert len(calls) == 1
    rich = await workshop_queries.details(settings, ["10"], description=True)
    assert rich["items"][0]["description"] == "Long text"
    account = "2"
    await workshop_queries.details(settings, ["10"])
    assert len(calls) == 3
    monkeypatch.setattr(steam_transport, "request", AsyncMock(return_value={"error": "Signed out"}))
    assert (await workshop_queries.details(settings, ["10"]))["items"] == []


async def test_search_filters_validation_and_partial_results(tmp_path, monkeypatch):
    settings = Settings(None, tmp_path / "db")
    remote = AsyncMock(
        return_value={
            "results": [{"title": "Harmony"}],
            "failed": [{"page": 2, "reason": "offline"}],
            "total": 99,
        }
    )
    monkeypatch.setattr(workshop_queries, "search", remote)
    result = await workshop.search(settings, "harmony", 80, "1.6", False, False, "relevance", 90)
    assert result["failed"][0]["page"] == 2
    assert remote.call_args.kwargs["required"] == ["Mod", "1.6"]
    assert remote.call_args.kwargs["excluded"] == ["Translation", "Scenario"]
    assert (
        "needs a query"
        in (await workshop.search(settings, "", 20, None, False, False, "relevance", 90))["error"]
    )
    assert (
        "limit"
        in (await workshop.search(settings, "a", 101, None, False, False, "recent", 90))["error"]
    )


async def test_failed_metadata_is_not_cached_and_refresh_bypasses_hits(tmp_path, monkeypatch):
    settings = Settings(None, tmp_path / "db")
    fail = True
    calls = 0

    async def request(_, action, **args):
        nonlocal calls
        if action == "probe":
            return {"account": "1"}
        calls += 1
        if fail:
            return {"account": "1", "items": [], "failed": [{"pfid": "10", "reason": "Timeout"}]}
        return {"account": "1", "items": [{"pfid": "10"}], "failed": []}

    monkeypatch.setattr(steam_transport, "request", request)
    await workshop_queries.details(settings, ["10"])
    fail = False
    await workshop_queries.details(settings, ["10"])
    await workshop_queries.details(settings, ["10"])
    assert calls == 2
    await workshop_queries.details(settings, ["10"], refresh=True)
    assert calls == 3


async def test_collection_filters_nested_and_wrong_game_items(tmp_path, monkeypatch):
    query = AsyncMock(
        side_effect=[
            {
                "items": [
                    {
                        "pfid": "1",
                        "file_type": 2,
                        "consumer_app_id": 294100,
                        "children": ["2", "3", "4", "5"],
                    }
                ],
                "failed": [],
            },
            {
                "items": [
                    {"pfid": "2", "file_type": 0, "consumer_app_id": 294100, "title": "Mod"},
                    {"pfid": "3", "file_type": 2, "consumer_app_id": 294100, "title": "Nested"},
                    {"pfid": "4", "file_type": 0, "consumer_app_id": 123, "title": "Other game"},
                ],
                "failed": [{"pfid": "5", "reason": "Unavailable"}],
            },
        ]
    )
    monkeypatch.setattr(workshop_queries, "details", query)
    result = await workshop.expand_collection(Settings(None, tmp_path), "1")
    assert result["pfids"] == ["2"]
    assert result["failed"][0]["pfid"] == "5"


async def test_unavailable_url_is_not_claimed_unpublished(tmp_path, monkeypatch):
    query = AsyncMock(
        return_value={"items": [], "failed": [{"pfid": "1", "reason": "Unavailable"}]}
    )
    monkeypatch.setattr(workshop_queries, "details", query)
    result = await workshop.resolve_url(Settings(None, tmp_path), "1")
    assert result["kind"] == "unknown"


async def test_update_states_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setattr(
        steam_transport,
        "request",
        AsyncMock(
            return_value={
                "items": [
                    {"pfid": "1", "subscribed": True, "installed": True, "needs_update": True},
                    {"pfid": "2", "subscribed": True, "installed": False, "needs_update": True},
                    {"pfid": "3", "subscribed": False, "installed": False},
                ]
            }
        ),
    )
    result = await workshop.check_updates(Settings(None, tmp_path), ["1", "2", "3"])
    assert result["outdated"] == ["1"]
    assert result["not_installed"] == ["2"]
    assert result["not_subscribed"] == ["3"]
