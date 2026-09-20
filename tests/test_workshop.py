from __future__ import annotations

from pathlib import Path

import pytest

from src.rimworld_tools import paths, workshop
from src.rimworld_tools.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(None, tmp_path / "dbs")


class TestGameVersion:
    def test_major_minor_from_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:

        monkeypatch.setattr(
            paths, "discover", lambda _s: paths.RimWorldPaths(version="1.6.4871 rev590")
        )
        assert workshop.detected_game_version(_settings(tmp_path)) == "1.6"

    def test_fallback_when_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:

        monkeypatch.setattr(paths, "discover", lambda _s: paths.RimWorldPaths())
        assert workshop.detected_game_version(_settings(tmp_path)) == "1.6"
