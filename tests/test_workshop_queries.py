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
