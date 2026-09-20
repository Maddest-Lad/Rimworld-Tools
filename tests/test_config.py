from __future__ import annotations

from pathlib import Path

import pytest

from src.rimworld_tools.config import RIMWORLD_APP_ID, Settings


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "RIMWORLD_TOOLS_STEAMCMD_PREFIX",
        "RIMWORLD_TOOLS_MODS_DIR",
        "RIMWORLD_TOOLS_DB_DIR",
        "RIMWORLD_TOOLS_MAX_DOWNLOAD_ITEMS",
        "STEAM_WEB_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_repo_local() -> None:
    s = Settings.from_env()
    assert s.steamcmd_prefix.name == "bin"
    assert s.mods_dir is None
    assert s.max_download_items == 50
    assert s.steam_web_api_key is None


def test_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RIMWORLD_TOOLS_STEAMCMD_PREFIX", str(tmp_path / "prefix"))
    monkeypatch.setenv("RIMWORLD_TOOLS_MODS_DIR", str(tmp_path / "Mods"))
    monkeypatch.setenv("STEAM_WEB_API_KEY", "deadbeef")
    s = Settings.from_env()
    assert s.steamcmd_prefix == tmp_path / "prefix"
    assert s.mods_dir == tmp_path / "Mods"
    assert s.steam_web_api_key == "deadbeef"


def test_bad_int_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIMWORLD_TOOLS_MAX_DOWNLOAD_ITEMS", "not-a-number")
    assert Settings.from_env().max_download_items == 50
    monkeypatch.setenv("RIMWORLD_TOOLS_MAX_DOWNLOAD_ITEMS", "0")
    assert Settings.from_env().max_download_items == 50


def test_settings_repr_redacts_the_api_key() -> None:
    settings = Settings(Path("prefix"), None, Path("db"), 50, "secret")
    assert "secret" not in repr(settings)


def test_derived_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RIMWORLD_TOOLS_STEAMCMD_PREFIX", str(tmp_path))
    s = Settings.from_env()
    assert s.steamcmd_dir == tmp_path / "steamcmd"
    assert s.force_install_dir == tmp_path / "steam"
    assert s.workshop_content_dir.name == str(RIMWORLD_APP_ID)
    assert s.acf_path.name == f"appworkshop_{RIMWORLD_APP_ID}.acf"
    assert s.console_log == tmp_path / "steamcmd" / "logs" / "console_log.txt"
    assert s.steamcmd_exe.name == "steamcmd.exe"
