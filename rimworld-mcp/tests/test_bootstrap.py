from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from src.rimworld_tools.paths import Found, RimWorldPaths

_BOOTSTRAP = Path(__file__).resolve().parents[2] / "bootstrap.py"
_spec = importlib.util.spec_from_file_location("bootstrap", _BOOTSTRAP)
bootstrap = importlib.util.module_from_spec(_spec)
sys.modules["bootstrap"] = bootstrap
_spec.loader.exec_module(bootstrap)


def test_plan_links_derives_logs_and_saves(tmp_path: Path) -> None:
    locallow = tmp_path / "LocalLow" / "RimWorld"
    (locallow / "Config").mkdir(parents=True)
    (locallow / "Saves").mkdir()
    discovered = RimWorldPaths(
        game_dir=Found(str(tmp_path / "RimWorld"), "test"),
        config_dir=Found(str(locallow / "Config"), "test"),
    )
    plans = {p.name: p for p in bootstrap.plan_links(discovered)}
    assert set(plans) == {"game", "config", "logs", "saves"}
    assert plans["logs"].target == locallow
    assert plans["saves"].target == locallow / "Saves"


def test_plan_links_skips_missing(tmp_path: Path) -> None:
    assert bootstrap.plan_links(RimWorldPaths()) == []


def test_merge_mcp_config_preserves_other_servers(tmp_path: Path) -> None:
    existing = {"mcpServers": {"other": {"command": "x"}}, "extra": 1}
    merged = bootstrap.merge_mcp_config(existing, tmp_path)
    assert merged["extra"] == 1
    assert merged["mcpServers"]["other"] == {"command": "x"}
    entry = merged["mcpServers"]["rimworld-tools"]
    assert entry["command"] == "uv"
    assert entry["args"] == [
        "--directory",
        str(tmp_path),
        "run",
        "-m",
        "src.rimworld_tools.server",
    ]
    # Idempotent: merging again is a no-op.
    assert bootstrap.merge_mcp_config(merged, tmp_path) == merged


def test_merge_mcp_config_from_nothing(tmp_path: Path) -> None:
    merged = bootstrap.merge_mcp_config(None, tmp_path)
    assert list(merged["mcpServers"]) == ["rimworld-tools"]
