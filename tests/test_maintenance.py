from __future__ import annotations

from pathlib import Path

from src.rimworld_tools import maintenance
from src.rimworld_tools.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        steamcmd_prefix=tmp_path / "prefix",
        mods_dir=tmp_path / "Mods",
        db_dir=tmp_path / "dbs",
        max_download_items=50,
        steam_web_api_key=None,
    )


async def test_maintenance_status_is_read_only(tmp_path: Path) -> None:
    args = maintenance._parser().parse_args(["status"])
    result = await maintenance._run(args, _settings(tmp_path))
    assert "steamcmd" in result and "databases" in result
