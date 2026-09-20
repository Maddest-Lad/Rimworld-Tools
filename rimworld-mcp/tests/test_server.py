from __future__ import annotations

from src.rimworld_tools.server import mcp


async def test_server_boots() -> None:
    assert mcp.name == "rimworld-tools"
    await mcp.list_tools()


async def test_every_tool_has_a_model_facing_docstring() -> None:
    """Tool docstrings are the description the model sees, so they must exist."""
    for tool in await mcp.list_tools():
        assert tool.description, f"{tool.name} has no description"


async def test_default_surface_excludes_maintenance_tools() -> None:
    names = {tool.name for tool in await mcp.list_tools()}
    assert len(names) == 15
    assert {"steamcmd_setup", "db_sync", "acf_repair", "cache_clear"}.isdisjoint(names)
    assert "environment_status" in names
    assert {"workshop_download", "workshop_delete"}.isdisjoint(names)
    assert {"workshop_subscribe", "workshop_unsubscribe"} <= names
    assert {"modlist_enable", "modlist_disable"} <= names
