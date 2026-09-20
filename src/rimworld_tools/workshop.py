from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import requests

from . import acf, advisories, paths, steamcmd, symlink, webapi
from . import cache as cache_mod
from .config import RIMWORLD_APP_ID, Settings

logger = logging.getLogger(__name__)


def _steam_client_acf(settings: Settings) -> Path | None:
    found = paths.discover(settings).steam_root
    if not found:
        return None
    p = Path(found.path) / "steamapps" / "workshop" / f"appworkshop_{RIMWORLD_APP_ID}.acf"
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


def mod_info(settings: Settings, pfids: list[str | int], refresh: bool = False) -> dict[str, Any]:
    good, bad = steamcmd._normalise_pfids(pfids)
    if not good:
        return {"error": "No valid published file ids given.", "hint": "Pass numeric pfids."}
    res = webapi.file_details(good, settings.steam_web_api_key, _cache(settings), refresh)
    ctx = advisories.Context.load(settings, detected_game_version(settings))
    items = []
    for item in res.items.values():
        found = _remote_advisories(ctx, item["pfid"], item["unpublished"])
        items.append({**item, "advisories": found} if found else item)
    out: dict[str, Any] = {"items": items, "failed": res.failed_ids + bad, "errors": res.errors}
    if summary := res.cache_summary():
        out["cache"] = summary
    if notice := ctx.db_notice():
        out["notice"] = notice
    return out


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
            "hint": "No installed Workshop items recorded. Run workshop_download or steamcmd_setup.",
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
                    "outdated": bool(rt and lt and rt > lt),
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
        out["hint"] = f"Update with workshop_download({steamcmd_outdated})."
    elif outdated:
        out["hint"] = "Outdated items are Steam-subscribed; the Steam client updates those itself."
    return out


def expand_collection(settings: Settings, url_or_id: str, refresh: bool = False) -> dict[str, Any]:
    pfid = webapi.parse_workshop_url(url_or_id)
    if not pfid:
        return {
            "error": f"Could not find an id in {url_or_id!r}.",
            "hint": "Pass a Workshop URL or numeric id.",
        }
    c = _cache(settings)
    try:
        children, cached_at = webapi.collection_children(
            pfid, settings.steam_web_api_key, c, refresh
        )
    except (requests.RequestException, ValueError) as exc:
        return {"error": webapi.redact(str(exc), settings.steam_web_api_key)}
    if children is None:
        return {"error": f"{pfid} is not a collection (or is private).", "collection": pfid}
    details = webapi.file_details(children, settings.steam_web_api_key, c, refresh)
    out: dict[str, Any] = {
        "collection": pfid,
        "count": len(children),
        "pfids": children,
        "items": [{"pfid": c, "title": details.items.get(c, {}).get("title")} for c in children],
        "lookup_failed": details.failed_ids,
        "hint": f"Download all with workshop_download(pfids=<pfids>) in batches ≤ {settings.max_download_items}.",
    }
    if cached_at is not None:
        out["cache"] = {
            "collection_cached_at": cache_mod.iso(cached_at),
            "note": "membership "
            + cache_mod.describe(cached_at)
            + ". Pass refresh=true to refetch.",
        }
        if summary := details.cache_summary():
            out["cache"]["titles"] = summary
    elif summary := details.cache_summary():
        out["cache"] = {"titles": summary}
    return out


def resolve_url(settings: Settings, url: str, refresh: bool = False) -> dict[str, Any]:
    pfid = webapi.parse_workshop_url(url)
    if not pfid:
        return {"error": f"No Workshop id found in {url!r}."}
    c = _cache(settings)
    try:
        children, cached_at = webapi.collection_children(
            pfid, settings.steam_web_api_key, c, refresh
        )
    except (requests.RequestException, ValueError):
        children, cached_at = None, None
    if children is not None:
        out: dict[str, Any] = {"pfid": pfid, "kind": "collection", "child_count": len(children)}
        if cached_at is not None:
            out["cache"] = {
                "cached_at": cache_mod.iso(cached_at),
                "note": cache_mod.describe(cached_at),
            }
        return out
    details = webapi.file_details([pfid], settings.steam_web_api_key, c, refresh)
    item = details.items.get(pfid)
    if item is None:
        return {"pfid": pfid, "kind": "unknown", "hint": "Lookup failed; try again."}
    if item["unpublished"]:
        private = webapi.is_private_or_deleted(pfid)
        out = {"pfid": pfid, "kind": "unpublished", "confirmed_private_or_deleted": private}
    else:
        out = {"pfid": pfid, "kind": "mod", "title": item["title"]}
    if summary := details.cache_summary():
        out["cache"] = summary
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


def search(
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
    if sort not in webapi.SORT_MODES:
        return {"error": f"Unknown sort {sort!r}.", "hint": f"One of {sorted(webapi.SORT_MODES)}."}
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

    if not settings.steam_web_api_key:
        return {
            "query": query,
            "filters": filters,
            "results": [],
            "browse_url": webapi.browse_url(query, required, excluded, sort, days),
            "hint": "No STEAM_WEB_API_KEY set; open browse_url and pass ids to resolve_workshop_url.",
        }
    try:
        out = webapi.search(
            query,
            settings.steam_web_api_key,
            limit,
            required,
            excluded,
            sort,
            days,
            _cache(settings),
            refresh,
        )
    except (requests.RequestException, ValueError) as exc:
        return {"error": webapi.redact(str(exc), settings.steam_web_api_key)}
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
    for pfid in good:
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
        return {"deleted": deleted, "failed": failed, "acf_backup": str(backup) if backup else None}
    return {"deleted": [], "failed": failed}
