from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastmcp import FastMCP

from . import paths
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
