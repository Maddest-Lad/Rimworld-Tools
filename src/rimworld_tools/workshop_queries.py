from __future__ import annotations

import asyncio
import copy
from typing import Any

from . import cache, steam_transport
from .config import Settings


async def details(
    settings: Settings,
    pfids: list[str],
    refresh: bool = False,
    description: bool = False,
    children: bool = False,
) -> dict[str, Any]:
    if not pfids:
        return {"items": [], "failed": []}
    session = await steam_transport.request(settings, "probe")
    if "error" in session:
        return {
            **session,
            "items": [],
            "failed": [{"pfid": p, "reason": session["error"]} for p in pfids],
        }
    account = session["account"]
    namespace = f"native_v1_{account}_details_{int(description)}_{int(children)}"
    store = cache.Cache(settings.cache_dir)
    lookup = await asyncio.to_thread(
        store.lookup, namespace, pfids, refresh, lambda _: cache.TTL_FILE_DETAILS
    )
    items = dict(lookup.hits)
    failed = []
    error = {}
    if lookup.misses:
        result = await steam_transport.request(
            settings,
            "details",
            account=account,
            pfids=lookup.misses,
            description=description,
            children=children,
        )
        if "error" in result:
            error = {k: result[k] for k in ("error", "hint") if k in result}
            failed = [{"pfid": p, "reason": result["error"]} for p in lookup.misses]
        else:
            fetched = {item["pfid"]: item for item in result["items"]}
            items.update(fetched)
            failed = result["failed"]
            await asyncio.to_thread(store.store, namespace, fetched)
    out = {
        **error,
        "items": [copy.deepcopy(items[p]) for p in pfids if p in items],
        "failed": failed,
    }
    if summary := lookup.summary(len(pfids)):
        out["cache"] = summary
    return out
