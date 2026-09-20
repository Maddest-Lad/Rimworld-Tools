from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import acf, advisories, paths, steamcmd, symlink, webapi, workshop_ids, workshop_queries
from . import cache as cache_mod
from .config import RIMWORLD_APP_ID, Settings
from .steam_client import SORT_MODES

logger = logging.getLogger(__name__)


def _steam_client_acf(settings: Settings) -> Path | None:
    found = paths.discover(settings).workshop_dir
    if not found:
        return None
    p = Path(found.path).parent.parent / f"appworkshop_{RIMWORLD_APP_ID}.acf"
    return p if p.is_file() else None


def installed_items(settings: Settings, include_steam_client: bool) -> dict[str, dict[str, Any]]:
    """ACF entries by pfid, tagged with source. SteamCMD wins if a pfid appears in both."""
    out: dict[str, dict[str, Any]] = {}
    if include_steam_client and (client := _steam_client_acf(settings)):
        for pfid, item in acf.items(acf.load(client)).items():
            out[pfid] = {"pfid": pfid, "source": "steam", "local_timeupdated": item.timeupdated}
    if settings.acf_path.is_file():
        for pfid, item in acf.items(acf.load(settings.acf_path)).items():
            out[pfid] = {"pfid": pfid, "source": "steamcmd", "local_timeupdated": item.timeupdated}
    return out


def _cache(settings: Settings) -> cache_mod.Cache:
    return cache_mod.Cache(settings.cache_dir)


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


def check_updates(
    settings: Settings,
    pfids: list[str | int] | None,
    include_steam_client: bool,
    refresh: bool = False,
) -> dict[str, Any]:
    local = installed_items(settings, include_steam_client)
    if pfids:
        good, _ = steamcmd._normalise_pfids(pfids)
        local = {p: local[p] for p in good if p in local}
        missing = [p for p in good if p not in local]
    else:
        missing = []
    if not local:
        return {
            "items": [],
            "outdated": [],
            "not_installed": missing,
            "hint": "No installed Workshop items recorded. Use workshop_subscribe, then wait for Steam to download them.",
        }
    remote = webapi.file_details(list(local), settings.steam_web_api_key, _cache(settings), refresh)
    ctx = advisories.Context.load(settings, detected_game_version(settings))
    items: list[dict[str, Any]] = []
    for pfid, rec in local.items():
        r = remote.items.get(pfid)
        row = dict(rec)
        if r is None:
            row.update({"title": None, "remote_time_updated": None, "outdated": None})
        else:
            rt = r["time_updated"]
            lt = rec["local_timeupdated"]
            row.update(
                {
                    "title": r["title"],
                    "remote_time_updated": rt,
                    "unpublished": r["unpublished"],
                    "outdated": rt > lt if rt is not None and lt is not None else None,
                }
            )
            if found := _remote_advisories(ctx, pfid, r["unpublished"]):
                row["advisories"] = found
        items.append(row)
    outdated = [i["pfid"] for i in items if i.get("outdated")]
    out: dict[str, Any] = {
        "items": items,
        "outdated": outdated,
        "not_installed": missing,
        "lookup_failed": remote.failed_ids,
        "errors": remote.errors,
    }
    if summary := remote.cache_summary():
        out["cache"] = summary
    steamcmd_outdated = [
        i["pfid"] for i in items if i.get("outdated") and i["source"] == "steamcmd"
    ]
    if steamcmd_outdated:
        out["hint"] = (
            f"Legacy SteamCMD copies are outdated: {steamcmd_outdated}. Subscribe with "
            "workshop_subscribe and select the Steam copies in RimWorld; local copies are not migrated automatically."
        )
    elif outdated:
        out["hint"] = "Outdated items are Steam-subscribed; the Steam client updates those itself."
    return out


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


def _delete_manifests(settings: Settings, manifests: set[str]) -> list[str]:
    removed: list[str] = []
    for m in manifests:
        p = settings.depotcache_dir / f"{RIMWORLD_APP_ID}_{m}.manifest"
        if p.is_file():
            p.unlink()
            removed.append(p.name)
    return removed


def delete(settings: Settings, pfids: list[str | int]) -> dict[str, Any]:
    """Remove item dir + BOTH ACF sections + depotcache manifest. Skipping the ACF purge makes
    SteamCMD believe the item is still installed and silently refuse to re-download it."""
    good, bad = steamcmd._normalise_pfids(pfids)
    if not good:
        return {"error": "No valid published file ids given."}
    running = acf.steam_processes_running(acf.STEAMCMD_PROCESSES)
    if running:
        return {
            "error": f"Refusing to delete while {', '.join(running)} is running.",
            "hint": "SteamCMD rewrites the ACF on exit and would resurrect the entries.",
        }
    mods_dir = steamcmd.resolve_mods_dir(settings)
    if mods_dir is None:
        return {"error": "Mods folder not found.", "hint": "Set RIMWORLD_TOOLS_MODS_DIR."}

    data = acf.load(settings.acf_path)
    deleted: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = [{"pfid": b, "reason": "not numeric"} for b in bad]
    skipped: list[dict[str, str]] = []
    managed = acf.items(data)
    for pfid in good:
        if pfid not in managed:
            skipped.append({"pfid": pfid, "reason": "not managed by SteamCMD (no ACF entry)"})
            continue
        target = mods_dir / pfid
        entry: dict[str, Any] = {"pfid": pfid, "dir_removed": False}
        if target.is_dir() and symlink.read_junction(target) is None:
            try:
                symlink.rmtree(target)
                entry["dir_removed"] = True
            except OSError as exc:
                failed.append({"pfid": pfid, "reason": f"could not remove {target}: {exc}"})
                continue
        entry["acf_removed"] = pfid in acf.items(data)
        manifests = acf.remove_items(data, [pfid])[pfid]
        entry["manifests_deleted"] = _delete_manifests(settings, manifests)
        deleted.append(entry)

    if deleted:
        backup = acf.save(settings.acf_path, data)
        return {
            "deleted": deleted,
            "failed": failed,
            "skipped": skipped,
            "acf_backup": str(backup) if backup else None,
        }
    return {"deleted": [], "failed": failed, "skipped": skipped}
