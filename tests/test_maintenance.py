from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from src.rimworld_tools import maintenance, steam_transport
from src.rimworld_tools.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        mods_dir=tmp_path / "Mods",
        db_dir=tmp_path / "dbs",
    )


async def test_maintenance_status_is_read_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(steam_transport, "request", AsyncMock(return_value={"ready": True}))
    args = maintenance._parser().parse_args(["status"])
    result = await maintenance._run(args, _settings(tmp_path))
    assert "steam" in result and "databases" in result
