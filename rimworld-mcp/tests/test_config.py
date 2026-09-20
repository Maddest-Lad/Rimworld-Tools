from __future__ import annotations

from src.rimworld_tools.config import Settings


def test_default_and_overridden_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("RIMWORLD_TOOLS_MODS_DIR", raising=False)
    monkeypatch.delenv("RIMWORLD_TOOLS_DB_DIR", raising=False)
    settings = Settings.from_env()
    assert settings.mods_dir is None
    assert settings.db_dir.name == "dbs"
    monkeypatch.setenv("RIMWORLD_TOOLS_MODS_DIR", str(tmp_path / "Mods"))
    monkeypatch.setenv("RIMWORLD_TOOLS_DB_DIR", str(tmp_path / "data"))
    settings = Settings.from_env()
    assert settings.mods_dir == tmp_path / "Mods"
    assert settings.cache_dir == tmp_path / "data" / "cache"


def test_blank_paths_use_defaults(monkeypatch):
    monkeypatch.setenv("RIMWORLD_TOOLS_MODS_DIR", "")
    monkeypatch.setenv("RIMWORLD_TOOLS_DB_DIR", "")
    settings = Settings.from_env()
    assert settings.mods_dir is None
    assert settings.db_dir.name == "dbs"
