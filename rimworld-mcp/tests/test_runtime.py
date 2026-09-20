from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.rimworld_tools import locking, runtime
from src.rimworld_tools.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        mods_dir=tmp_path / "Mods",
        db_dir=tmp_path / "dbs",
    )


class TestRuntime:
    async def test_mutation_returns_a_busy_result_when_the_file_lock_is_held(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(locking.WindowsFileLock, "acquire", lambda *_: False)
        active = runtime.Runtime(_settings(tmp_path))
        async with active.mutation() as blocked:
            assert blocked is not None
            assert "still using" in blocked["error"]

    async def test_subscription_mutations_are_serialized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = 0
        running = 0
        maximum = 0

        active = runtime.Runtime(_settings(tmp_path))
        monkeypatch.setattr(locking.WindowsFileLock, "acquire", lambda *_: True)
        monkeypatch.setattr(locking.WindowsFileLock, "release", lambda *_: None)

        async def change() -> None:
            nonlocal calls, maximum, running
            async with active.mutation() as blocked:
                assert blocked is None
                calls += 1
                running += 1
                maximum = max(maximum, running)
                await asyncio.sleep(0)
                running -= 1

        await asyncio.gather(change(), change())
        assert calls == 2
        assert maximum == 1
