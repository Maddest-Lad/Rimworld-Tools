from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.rimworld_tools import runtime, steamcmd
from src.rimworld_tools.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        steamcmd_prefix=tmp_path / "prefix",
        mods_dir=tmp_path / "Mods",
        db_dir=tmp_path / "dbs",
        max_download_items=50,
        steam_web_api_key=None,
    )


class TestRuntime:
    async def test_download_preparation_is_serialized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = 0
        running = 0
        maximum = 0

        async def setup(_: Settings) -> dict[str, object]:
            nonlocal calls, maximum, running
            calls += 1
            running += 1
            maximum = max(maximum, running)
            await asyncio.sleep(0)
            running -= 1
            return {"installed": True, "junction_ok": True}

        monkeypatch.setattr(steamcmd, "setup", setup)
        active = runtime.Runtime(_settings(tmp_path))
        first, second = await asyncio.gather(
            active.ensure_download_environment(), active.ensure_download_environment()
        )
        assert first is None and second is None
        assert calls == 2
        assert maximum == 1

    async def test_download_preparation_returns_setup_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def setup(_: Settings) -> dict[str, object]:
            return {"error": "Mods folder missing"}

        monkeypatch.setattr(steamcmd, "setup", setup)
        assert await runtime.Runtime(_settings(tmp_path)).ensure_download_environment() == {
            "error": "Mods folder missing"
        }
