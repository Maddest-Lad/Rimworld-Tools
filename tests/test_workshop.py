from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.rimworld_tools import acf, paths, webapi, workshop
from src.rimworld_tools.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        steamcmd_prefix=tmp_path,
        mods_dir=tmp_path / "Mods",
        db_dir=tmp_path / "dbs",
        max_download_items=50,
        steam_web_api_key=None,
    )


def _acf_with(pfid: str, timeupdated: int, manifest: str) -> dict:
    data = acf.empty()
    node = acf.root(data)
    node["WorkshopItemsInstalled"][pfid] = {
        "size": "1",
        "timeupdated": str(timeupdated),
        "manifest": manifest,
    }
    node["WorkshopItemDetails"][pfid] = {"manifest": manifest, "timeupdated": str(timeupdated)}
    return data


def _remote(items: dict[str, dict[str, Any]], failed: list[str] | None = None):
    def fake(pfids: list[str], key: str | None = None, *_: object) -> webapi.ChunkedResult:
        return webapi.ChunkedResult(
            items={p: items[p] for p in pfids if p in items}, failed_ids=failed or []
        )

    return fake


class TestDelete:
    @pytest.fixture
    def installed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
        s = _settings(tmp_path)
        (s.mods_dir / "111" / "About").mkdir(parents=True)
        (s.mods_dir / "111" / "About" / "About.xml").write_text("<x/>", encoding="utf-8")
        s.depotcache_dir.mkdir(parents=True)
        (s.depotcache_dir / "294100_m111.manifest").write_text("", encoding="utf-8")
        (s.depotcache_dir / "294100_other.manifest").write_text("", encoding="utf-8")
        s.acf_path.parent.mkdir(parents=True)
        acf.save(s.acf_path, _acf_with("111", 1, "m111"))
        monkeypatch.setattr(acf, "steam_processes_running", lambda *_: [])
        return s

    def test_three_part_cleanup(self, installed: Settings) -> None:
        out = workshop.delete(installed, ["111"])
        entry = out["deleted"][0]
        assert entry == {
            "pfid": "111",
            "dir_removed": True,
            "acf_removed": True,
            "manifests_deleted": ["294100_m111.manifest"],
        }
        assert not (installed.mods_dir / "111").exists()
        assert acf.items(acf.load(installed.acf_path)) == {}
        assert (installed.depotcache_dir / "294100_other.manifest").exists()
        assert Path(out["acf_backup"]).is_file()

    def test_unknown_pfid_is_not_treated_as_managed(self, installed: Settings) -> None:
        unmanaged = installed.mods_dir / "999"
        unmanaged.mkdir()
        out = workshop.delete(installed, ["999"])
        assert out["deleted"] == []
        assert out["skipped"] == [
            {"pfid": "999", "reason": "not managed by SteamCMD (no ACF entry)"}
        ]
        assert unmanaged.exists()

    def test_refuses_while_steamcmd_runs(
        self, installed: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(acf, "steam_processes_running", lambda *_: ["steamcmd.exe"])
        out = workshop.delete(installed, ["111"])
        assert "Refusing" in out["error"]
        assert (installed.mods_dir / "111").exists()

    def test_never_removes_a_junction_in_mods_dir(
        self, installed: Settings, tmp_path: Path
    ) -> None:
        from src.rimworld_tools import symlink

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "keep.txt").write_text("", encoding="utf-8")
        symlink.ensure_junction(installed.mods_dir / "222", elsewhere)
        data = acf.load(installed.acf_path)
        acf.root(data)["WorkshopItemsInstalled"]["222"] = {"manifest": "m222"}
        acf.save(installed.acf_path, data)
        out = workshop.delete(installed, ["222"])
        assert out["deleted"][0]["dir_removed"] is False
        assert (elsewhere / "keep.txt").exists()


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
