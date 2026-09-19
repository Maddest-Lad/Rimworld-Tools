from __future__ import annotations

from src.rimworld_tools.server import mcp


async def test_server_boots() -> None:
    assert mcp.name == "rimworld-tools"
    await mcp.list_tools()


async def test_every_tool_has_a_model_facing_docstring() -> None:
    """Tool docstrings are the description the model sees, so they must exist."""
    for tool in await mcp.list_tools():
        assert tool.description, f"{tool.name} has no description"
