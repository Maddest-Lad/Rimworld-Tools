from __future__ import annotations

import logging
from typing import Any

from . import advisories, paths, steam_transport, workshop_ids, workshop_queries
from .config import RIMWORLD_APP_ID, Settings
from .steam_client import SORT_MODES

logger = logging.getLogger(__name__)


async def mod_info(
    settings: Settings,
    pfids: list[str | int],
    refresh: bool = False,
    include_description: bool = False,
) -> dict[str, Any]:
    good, bad = workshop_ids.normalise(pfids)
    if not good:
        return {
            "error": "No valid published file ids given.",
            "hint": "Pass positive numeric pfids.",
        }
    result = await workshop_queries.details(settings, good, refresh, include_description)
    ctx = advisories.Context.load(settings, detected_game_version(settings))
    for item in result["items"]:
        if found := _remote_advisories(ctx, item["pfid"], False):
            item["advisories"] = found
    result["failed"].extend({"pfid": p, "reason": "Invalid Workshop id."} for p in bad)
    if notice := ctx.db_notice():
        result["notice"] = notice
    return result


def _remote_advisories(
    ctx: advisories.Context, pfid: str, unpublished: bool
) -> list[dict[str, Any]]:
    found = [ctx.replacement(pfid, unpublished), ctx.blacklist(pfid)]
    return [a.to_dict() for a in found if a is not None]


async def check_updates(settings: Settings, pfids: list[str | int] | None = None) -> dict[str, Any]:
    good, bad = workshop_ids.normalise(pfids) if pfids is not None else (None, [])
    result = await steam_transport.request(settings, "state", pfids=good)
    result.pop("account", None)
    if "error" in result:
        return result
    items = result["items"]
    return {
        "items": items,
        "outdated": [r["pfid"] for r in items if r.get("installed") and r.get("needs_update")],
        "not_installed": [
            r["pfid"] for r in items if r.get("subscribed") and r.get("installed") is False
        ],
        "not_subscribed": [r["pfid"] for r in items if not r["subscribed"]],
        "failed": [{"pfid": p, "reason": "Invalid Workshop id."} for p in bad],
        "hint": "Live Steam client state; Steam handles downloads and updates. installed_at is the installation timestamp, not the Workshop publication time.",
    }


async def expand_collection(
    settings: Settings, url_or_id: str, refresh: bool = False
) -> dict[str, Any]:
    pfid = workshop_ids.parse_url(url_or_id)
    if not pfid:
        return {
            "error": "No valid Workshop id found.",
            "hint": "Pass a Steam Workshop URL or numeric id.",
        }
    parent = await workshop_queries.details(settings, [pfid], refresh, children=True)
    if not parent["items"]:
        return parent
    item = parent["items"][0]
    if item["file_type"] != 2 or item["consumer_app_id"] != RIMWORLD_APP_ID:
        return {
            "error": "This item is not a RimWorld collection.",
            "hint": "Pass a RimWorld collection id.",
        }
    details = await workshop_queries.details(settings, item["children"], refresh)
    mods = [
        row
        for row in details["items"]
        if row["file_type"] == 0 and row["consumer_app_id"] == RIMWORLD_APP_ID
    ]
    result = {
        "collection": pfid,
        "count": len(mods),
        "pfids": [row["pfid"] for row in mods],
        "items": [{"pfid": row["pfid"], "title": row["title"]} for row in mods],
        "failed": details["failed"],
        "hint": "Subscribe with workshop_subscribe(pfids=<pfids>) in batches of at most 50.",
    }
    if "error" in details:
        result.update({k: details[k] for k in ("error", "hint") if k in details})
    if "cache" in parent or "cache" in details:
        result["cache"] = {"membership": parent.get("cache"), "items": details.get("cache")}
    return result


async def resolve_url(settings: Settings, url: str, refresh: bool = False) -> dict[str, Any]:
    pfid = workshop_ids.parse_url(url)
    if not pfid:
        return {
            "error": "No valid Workshop id found.",
            "hint": "Pass a Steam Workshop URL or numeric id.",
        }
    result = await workshop_queries.details(settings, [pfid], refresh)
    if not result["items"]:
        return {**result, "pfid": pfid, "kind": "unknown"}
    item = result["items"][0]
    kind = {0: "mod", 2: "collection"}.get(item["file_type"], "other")
    if item["consumer_app_id"] != RIMWORLD_APP_ID:
        kind = "other_game"
    out = {"pfid": pfid, "kind": kind, "title": item["title"]}
    if "cache" in result:
        out["cache"] = result["cache"]
    return out


_FALLBACK_GAME_VERSION = "1.6"


def detected_game_version(settings: Settings) -> str:
    """major.minor of the installed game, e.g. '1.6'; falls back if RimWorld isn't found."""
    v = paths.discover(settings).version
    if v:
        parts = v.split(".")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"{parts[0]}.{parts[1]}"
    return _FALLBACK_GAME_VERSION


async def search(
    settings: Settings,
    query: str,
    limit: int,
    game_version: str | None,
    include_translations: bool,
    include_scenarios: bool,
    sort: str,
    days: int,
    refresh: bool = False,
) -> dict[str, Any]:
    if sort not in SORT_MODES:
        return {"error": f"Unknown sort {sort!r}.", "hint": f"One of {sorted(SORT_MODES)}."}
    if sort == "relevance" and not query.strip():
        return {"error": "relevance sort needs a query.", "hint": "Use sort='trend' to browse."}

    version = game_version or detected_game_version(settings)
    required = ["Mod"] + ([version] if version.lower() != "any" else [])
    excluded = ([] if include_translations else ["Translation"]) + (
        [] if include_scenarios else ["Scenario"]
    )
    filters = {"required_tags": required, "excluded_tags": excluded, "sort": sort}
    if sort == "trend":
        filters["days"] = days

    if not 1 <= limit <= 100:
        return {"error": "limit must be between 1 and 100.", "hint": "Use a smaller query."}
    if not 1 <= days <= 365:
        return {"error": "days must be between 1 and 365.", "hint": "Use a supported trend window."}
    if "\0" in query or len(query.encode("utf-8")) > 4096:
        return {
            "error": "Search text is invalid or too long.",
            "hint": "Use at most 4096 UTF-8 bytes without NUL characters.",
        }
    out = await workshop_queries.search(
        settings,
        refresh,
        query=query,
        limit=limit,
        required=required,
        excluded=excluded,
        sort=sort,
        days=days,
    )
    out["filters"] = filters
    # Steam's text search ranks rather than filters: a nonsense query still returns `total`
    # in the tens of thousands. Flag it when no returned title contains any query word.
    tokens = [t for t in query.lower().split() if len(t) > 2]
    titles = [(r.get("title") or "").lower() for r in out.get("results", [])]
    if tokens and titles and not any(t in title for t in tokens for title in titles):
        out["hint"] = (
            "No returned title contains a query word; treat this as no match. "
            "`total` is Steam's ranked candidate count, not a match count."
        )
    return out
