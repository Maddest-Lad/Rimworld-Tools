from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import FastMCP

from . import acf, paths, steamcmd
from .config import Settings

logger = logging.getLogger(__name__)

mcp = FastMCP("rimworld-tools")


@mcp.tool
async def rimworld_locate() -> dict[str, Any]:
    """
    Find the RimWorld install, Mods folder, config folder and Steam Workshop content folder.
    Each result carries the provenance of how it was found; nulls mean it could not be located.
    Example: rimworld_locate()
    """
    settings = Settings.from_env()
    found = await asyncio.to_thread(paths.discover, settings)
    result = found.to_dict()
    if found.game_dir is None:
        result["hint"] = (
            "RimWorld was not found. Set RIMWORLD_TOOLS_MODS_DIR to the Mods folder, "
            "or install RimWorld via Steam so libraryfolders.vdf lists AppID 294100."
        )
    return result


@mcp.tool
async def steamcmd_status() -> dict[str, Any]:
    """
    Cheap health check: is SteamCMD installed, is the Workshop junction pointing at the Mods
    folder, how many items does the ACF record. Call this before download/delete tools.
    Example: steamcmd_status()
    """
    return await asyncio.to_thread(steamcmd.status, Settings.from_env())


@mcp.tool
async def steamcmd_setup(
    force_reinstall: bool = False, force_junction: bool = False
) -> dict[str, Any]:
    """
    Install SteamCMD into the prefix and junction its Workshop output folder to the Mods folder.
    Idempotent. A fresh install also runs SteamCMD's self-update, which takes ~30-60s.
    force_junction replaces whatever occupies the junction path; force_reinstall re-downloads.
    Example: steamcmd_setup()
    """
    return await steamcmd.setup(Settings.from_env(), force_reinstall, force_junction)


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
    return await steamcmd.download(
        Settings.from_env(), pfids, validate=validate, clear_cache=clear_depot_cache
    )


@mcp.tool
async def clear_depot_cache() -> dict[str, Any]:
    """
    Delete SteamCMD's depotcache. First remediation for downloads that report success but
    write nothing, or fail with disk/manifest errors.
    Example: clear_depot_cache()
    """
    return await asyncio.to_thread(steamcmd.clear_depot_cache, Settings.from_env())


@mcp.tool
async def acf_repair(dry_run: bool = True) -> dict[str, Any]:
    """
    Remove ACF entries for Workshop items no longer on disk. Stale entries make SteamCMD skip
    re-downloads silently. dry_run lists orphans without writing; the write keeps a .backup.
    Example: acf_repair(dry_run=False)
    """
    settings = Settings.from_env()
    return await asyncio.to_thread(
        acf.repair, settings.acf_path, settings.workshop_content_dir, dry_run
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
