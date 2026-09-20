from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import FastMCP

from . import modlist, mods, paths, runtime, subscriptions, workshop
from .config import Settings

logger = logging.getLogger(__name__)

mcp = FastMCP("rimworld-tools")


def _settings() -> Settings:
    return runtime.get().settings


@mcp.tool
async def environment_status() -> dict[str, Any]:
    """
    Show RimWorld discovery and Steam client availability in one compact read-only result.
    Example: environment_status()
    """
    settings = _settings()
    status = await subscriptions.status(settings)
    status["rimworld"] = (await asyncio.to_thread(paths.discover, settings)).to_dict()
    return status


@mcp.tool
async def workshop_subscribe(pfids: list[str | int]) -> dict[str, Any]:
    """
    Subscribe the signed-in Steam account to RimWorld mods (up to 50 ids).
    Steam must be running; downloads happen asynchronously after subscription succeeds.
    Example: workshop_subscribe(["2009463077", "1631756268"])
    """
    active = runtime.get()
    async with active.mutation() as blocked:
        if blocked is not None:
            return blocked
        return await subscriptions.change(_settings(), pfids, subscribe=True)


@mcp.tool
async def list_installed_mods(
    source: str | None = None,
    package_ids: list[str] | None = None,
    detail: bool = False,
    include_invalid: bool = False,
) -> dict[str, Any]:
    """
    Every mod on disk with packageId, name, source (ludeon|steam|git|local), pfid, version_ok
    and active (whether ModsConfig.xml lists it). Compact by default — detail=true adds paths,
    authors, dependencies and load rules. Filter by source or package_ids to keep the payload
    small; duplicates are reported separately.
    Example: list_installed_mods(source="steam", detail=true)
    """
    await runtime.get().ensure_community_data()
    settings = _settings()
    active = await asyncio.to_thread(modlist.active_ids, settings)
    return await asyncio.to_thread(
        mods.inventory, settings, source, package_ids, detail, include_invalid, active
    )


@mcp.tool
async def workshop_mod_info(
    pfids: list[str | int], refresh: bool = False, include_description: bool = False
) -> dict[str, Any]:
    """
    Title, update time, size and tags for Workshop items through the signed-in Steam client.
    include_description=true adds Steam's description, flagging possible native buffer truncation.
    Cached per item for 6h; responses say what came from cache and when. refresh=true refetches.
    Example: workshop_mod_info(["2009463077"])
    """
    await runtime.get().ensure_community_data()
    return await workshop.mod_info(_settings(), pfids, refresh, include_description)


@mcp.tool
async def check_mod_updates(pfids: list[str | int] | None = None) -> dict[str, Any]:
    """
    Show live Steam subscription, installation and download state for RimWorld mods.
    Defaults to all subscriptions; outdated lists installed copies that Steam says need updates.
    Example: check_mod_updates()
    """
    return await workshop.check_updates(_settings(), pfids)


@mcp.tool
async def collection_expand(collection_url_or_id: str, refresh: bool = False) -> dict[str, Any]:
    """
    List the mods inside a Workshop collection (nested collections are filtered out).
    Membership and metadata are cached 6h per Steam account; refresh=true refetches.
    Example: collection_expand("https://steamcommunity.com/sharedfiles/filedetails/?id=3521998684")
    """
    await runtime.get().ensure_community_data()
    return await workshop.expand_collection(_settings(), collection_url_or_id, refresh)


@mcp.tool
async def resolve_workshop_url(url: str, refresh: bool = False) -> dict[str, Any]:
    """
    Resolve a Workshop URL or id to mod, collection, other, other_game, or unknown.
    Unavailable items return a reason; a failed lookup does not prove an item is unpublished.
    Example: resolve_workshop_url("https://steamcommunity.com/sharedfiles/filedetails/?id=2009463077")
    """
    return await workshop.resolve_url(_settings(), url, refresh)


@mcp.tool
async def workshop_search(
    query: str = "",
    limit: int = 20,
    game_version: str = "1.6",
    include_translations: bool = False,
    include_scenarios: bool = False,
    sort: str = "relevance",
    days: int = 365,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    Search the RimWorld Workshop. Defaults filter to Mod items tagged with the installed game
    Results are cached 1h per distinct query+filters; refresh=true refetches.
    sort: relevance (needs query) | trend (uses days) | recent | top | updated.
    Example: workshop_search("vanilla expanded framework")
    Example: workshop_search(sort="trend", days=30, limit=10)
    """
    return await workshop.search(
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
async def workshop_unsubscribe(pfids: list[str | int]) -> dict[str, Any]:
    """
    Unsubscribe the signed-in Steam account from RimWorld mods (up to 50 ids).
    Steam handles removal after the game exits; local Mods copies are untouched.
    Example: workshop_unsubscribe(["2009463077"])
    """
    active = runtime.get()
    async with active.mutation() as blocked:
        if blocked is not None:
            return blocked
        return await subscriptions.change(_settings(), pfids, subscribe=False)


@mcp.tool
async def sort_modlist(dry_run: bool = True) -> dict[str, Any]:
    """
    Compute a RimWorld load order for the active mods in ModsConfig.xml: Core/DLC/Harmony first,
    known frameworks next, everything else topologically by About.xml + community + user rules,
    loadBottom mods last. dry_run returns the order without writing; a write snapshots first.
    On a dependency cycle nothing is written and the cycle's rules are returned with sources.
    Example: sort_modlist(dry_run=false)
    """
    active = runtime.get()
    await active.ensure_community_data()
    if dry_run:
        return await asyncio.to_thread(modlist.sort_modlist, _settings(), True)
    async with active.mutation("modlist") as blocked:
        if blocked is not None:
            return blocked
        return await asyncio.to_thread(modlist.sort_modlist, _settings(), False)


@mcp.tool
async def modlist_enable(ids: list[str], dry_run: bool = True) -> dict[str, Any]:
    """
    Activate installed mods in ModsConfig.xml by packageId or Workshop pfid (up to 100).
    New entries go to the end of the load order, so run sort_modlist afterwards. Reports
    dependency_issues and incompatible_active_pairs the change introduces; not-installed mods
    fail with a workshop_subscribe action. dry_run previews; a write snapshots first and refuses
    while RimWorld is running.
    Example: modlist_enable(["dubwise.dubsbadhygiene", "2009463077"], dry_run=false)
    """
    return await _change_active(ids, enable=True, dry_run=dry_run)


@mcp.tool
async def modlist_disable(ids: list[str], dry_run: bool = True) -> dict[str, Any]:
    """
    Deactivate mods in ModsConfig.xml by packageId or Workshop pfid (up to 100); Core cannot be
    disabled and installed files are untouched. Reports still-active mods that depended on what
    was removed. dry_run previews; a write snapshots first and refuses while RimWorld is running.
    Example: modlist_disable(["author.brokenmod"], dry_run=false)
    """
    return await _change_active(ids, enable=False, dry_run=dry_run)


async def _change_active(ids: list[str], enable: bool, dry_run: bool) -> dict[str, Any]:
    active = runtime.get()
    await active.ensure_community_data()
    if dry_run:
        return await asyncio.to_thread(modlist.change_active, _settings(), ids, enable, True)
    async with active.mutation("modlist") as blocked:
        if blocked is not None:
            return blocked
        return await asyncio.to_thread(modlist.change_active, _settings(), ids, enable, False)


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
