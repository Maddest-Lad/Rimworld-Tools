from __future__ import annotations

from typing import Any

from . import steam_transport, workshop_ids
from .config import Settings

MAX_ITEMS = 50


async def status(settings: Settings) -> dict[str, Any]:
    return await steam_transport.request(settings, "probe")


async def change(settings: Settings, pfids: list[str | int], subscribe: bool) -> dict[str, Any]:
    good, bad = workshop_ids.normalise(pfids)
    failed = [{"pfid": p, "reason": "Expected a positive 64-bit Workshop id."} for p in bad]
    if len(good) > MAX_ITEMS:
        return {
            "error": f"At most {MAX_ITEMS} items per subscription call.",
            "hint": "Split the list into batches.",
        }
    if not good:
        return {"succeeded": [], "failed": failed}
    result = await steam_transport.request(
        settings, "subscribe" if subscribe else "unsubscribe", pfids=good
    )
    result.pop("account", None)
    if "error" in result:
        return {
            **result,
            "succeeded": [],
            "failed": failed + [{"pfid": p, "reason": result["error"]} for p in good],
        }
    result["failed"] = failed + result["failed"]
    result["hint"] = (
        "Subscriptions confirmed or already satisfied; Steam downloads asynchronously."
        if subscribe
        else "Unsubscriptions confirmed or already satisfied; Steam manages removal after the game exits. Local Mods copies are untouched."
    )
    return result
