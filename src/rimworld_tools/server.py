from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import FastMCP

from . import modlist, mods, paths, runtime, steamcmd, workshop
from .config import Settings

logger = logging.getLogger(__name__)

mcp = FastMCP("rimworld-tools")


def _settings() -> Settings:
    return runtime.get().settings


@mcp.tool
async def environment_status() -> dict[str, Any]:
    """
    Show RimWorld discovery plus SteamCMD readiness in one compact read-only result.
    Example: environment_status()
    """
    settings = _settings()
    status = await asyncio.to_thread(steamcmd.status, settings)
    status["rimworld"] = (await asyncio.to_thread(paths.discover, settings)).to_dict()
    return status


@mcp.tool
async def workshop_download(
    pfids: list[str | int], validate: bool = False, clear_depot_cache: bool = False
) -> dict[str, Any]:
    """
    Download or update Workshop mods by published file id straight into the Mods folder.
    Blocks until done; batches of 25 internally. Returns succeeded and failed with reasons.
    validate re-hashes existing files (slow, repairs corrupt installs).
    Example: workshop_download(["2009463077", "1631756268"])
    """
    active = runtime.get()
    async with active.mutation() as blocked:
        if blocked is not None:
            return blocked
        prepared = await active.ensure_download_environment()
        if prepared is not None:
            return prepared
        return await steamcmd.download(
            _settings(), pfids, validate=validate, clear_cache=clear_depot_cache
        )


@mcp.tool
async def list_installed_mods(
    source: str | None = None,
    package_ids: list[str] | None = None,
    detail: bool = False,
    include_invalid: bool = False,
) -> dict[str, Any]:
    """
    Every mod on disk with packageId, name, source (ludeon|steam|steamcmd|git|local), pfid and
    version_ok. Compact by default — detail=true adds paths, authors, dependencies and load rules.
    Filter by source or package_ids to keep the payload small; duplicates are reported separately.
    Example: list_installed_mods(source="steamcmd", detail=true)
    """
    await runtime.get().ensure_community_data()
    return await asyncio.to_thread(
        mods.inventory, _settings(), source, package_ids, detail, include_invalid
    )


@mcp.tool
async def workshop_mod_info(pfids: list[str | int], refresh: bool = False) -> dict[str, Any]:
    """
    Title, update time, size, tags and unpublished flag for Workshop items. Keyless.
    Cached per item for 6h; responses say what came from cache and when. refresh=true refetches.
    Example: workshop_mod_info(["2009463077"])
    """
    await runtime.get().ensure_community_data()
    return await asyncio.to_thread(workshop.mod_info, _settings(), pfids, refresh)


@mcp.tool
async def check_mod_updates(
    pfids: list[str | int] | None = None, include_steam_client: bool = True, refresh: bool = False
) -> dict[str, Any]:
    """
    Compare each installed item's ACF timestamp with the Workshop's. Defaults to everything
    installed via SteamCMD and (optionally) the Steam client. Returns the outdated pfid list.
    Workshop data is cached 6h per item; refresh=true forces a live re-check of all of them.
    Example: check_mod_updates()
    """
    await runtime.get().ensure_community_data()
    return await asyncio.to_thread(
        workshop.check_updates, _settings(), pfids, include_steam_client, refresh
    )


@mcp.tool
async def collection_expand(collection_url_or_id: str, refresh: bool = False) -> dict[str, Any]:
    """
    List the mods inside a Workshop collection (nested collections are filtered out).
    Membership is cached 24h; refresh=true refetches.
    Example: collection_expand("https://steamcommunity.com/sharedfiles/filedetails/?id=2896394545")
    """
    await runtime.get().ensure_community_data()
    return await asyncio.to_thread(
        workshop.expand_collection, _settings(), collection_url_or_id, refresh
    )


@mcp.tool
async def resolve_workshop_url(url: str, refresh: bool = False) -> dict[str, Any]:
    """
    Turn a pasted Workshop URL or id into {pfid, kind: mod|collection|unpublished}.
    Example: resolve_workshop_url("https://steamcommunity.com/sharedfiles/filedetails/?id=2009463077")
    """
    return await asyncio.to_thread(workshop.resolve_url, _settings(), url, refresh)


@mcp.tool
async def workshop_search(
    query: str = "",
    limit: int = 20,
    game_version: str | None = None,
    include_translations: bool = False,
    include_scenarios: bool = False,
    sort: str = "relevance",
    days: int = 90,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    Search the RimWorld Workshop. Defaults filter to Mod items tagged with the installed game
    version (e.g. 1.6) and exclude Translation/Scenario items; pass game_version="any" to lift it.
    Results are cached 1h per distinct query+filters; refresh=true refetches.
    sort: relevance (needs query) | trend (uses days) | recent | top | updated.
    Example: workshop_search("vanilla expanded framework")
    Example: workshop_search(sort="trend", days=30, limit=10)
    """
    return await asyncio.to_thread(
        workshop.search,
        _settings(),
        query,
        limit,
        game_version,
        include_translations,
        include_scenarios,
        sort,
        days,
        refresh,
    )


@mcp.tool
async def workshop_delete(pfids: list[str | int]) -> dict[str, Any]:
    """
    Delete SteamCMD-managed mods: removes the folder, purges both ACF sections and the depot
    manifest so a later re-download actually downloads. Refuses while steamcmd.exe is running.
    Example: workshop_delete(["2009463077"])
    """
    active = runtime.get()
    async with active.mutation() as blocked:
        if blocked is not None:
            return blocked
        return await asyncio.to_thread(workshop.delete, _settings(), pfids)


@mcp.tool
async def sort_modlist(dry_run: bool = True) -> dict[str, Any]:
    """
    Compute a RimWorld load order for the active mods in ModsConfig.xml: Core/DLC/Harmony first,
    known frameworks next, everything else topologically by About.xml + community + user rules,
    loadBottom mods last. dry_run returns the order without writing; a write snapshots first.
    On a dependency cycle nothing is written and the cycle's rules are returned with sources.
    Example: sort_modlist(dry_run=false)
    """
    await runtime.get().ensure_community_data()
    return await asyncio.to_thread(modlist.sort_modlist, _settings(), dry_run)


@mcp.tool
async def diagnose_cycles() -> dict[str, Any]:
    """
    Report load-order cycles among active mods, each edge tagged with the rule source that made it
    (about:<mod>, community, user), plus incompatible active pairs and missing dependencies.
    Example: diagnose_cycles()
    """
    await runtime.get().ensure_community_data()
    return await asyncio.to_thread(modlist.diagnose, _settings())


@mcp.tool
async def modlist_snapshot(note: str = "", list_only: bool = False) -> dict[str, Any]:
    """
    Save the current ModsConfig.xml active list as a named snapshot, or list existing snapshots.
    Example: modlist_snapshot("before adding VE mods")
    """
    settings = _settings()
    if list_only:
        return {"snapshots": await asyncio.to_thread(modlist.list_snapshots, settings)}
    return await asyncio.to_thread(modlist.snapshot, settings, note)


@mcp.tool
async def modlist_diff(old: str = "latest", new: str = "current") -> dict[str, Any]:
    """
    Added/removed/moved mods between two lists. Refs: "current" (ModsConfig.xml), "latest"
    (newest snapshot) or a snapshot id.
    Example: modlist_diff("latest", "current")
    """
    return await asyncio.to_thread(modlist.diff, _settings(), old, new)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    runtime.configure()
    mcp.run()


if __name__ == "__main__":
    main()
