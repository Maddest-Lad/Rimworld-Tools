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


class TestCheckUpdates:
    def test_reads_client_acf_from_the_game_library(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _settings(tmp_path)
        workshop_root = tmp_path / "secondary" / "steamapps" / "workshop"
        content = workshop_root / "content" / "294100"
        content.mkdir(parents=True)
        acf.save(workshop_root / "appworkshop_294100.acf", _acf_with("1", 100, "m1"))
        monkeypatch.setattr(
            paths,
            "discover",
            lambda _: paths.RimWorldPaths(
                workshop_dir=paths.Found(str(content), "secondary library")
            ),
        )
        assert workshop.installed_items(s, include_steam_client=True)["1"]["source"] == "steam"

    def test_flags_outdated_only_when_remote_is_newer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _settings(tmp_path)
        s.acf_path.parent.mkdir(parents=True)
        data = _acf_with("1", 100, "m1")
        acf.root(data)["WorkshopItemsInstalled"]["2"] = {"timeupdated": "500", "manifest": "m2"}
        acf.save(s.acf_path, data)
        monkeypatch.setattr(
            webapi,
            "file_details",
            _remote(
                {
                    "1": {"title": "Old", "time_updated": 200, "unpublished": False},
                    "2": {"title": "Fresh", "time_updated": 400, "unpublished": False},
                }
            ),
        )
        out = workshop.check_updates(s, None, include_steam_client=False)
        assert out["outdated"] == ["1"]
        assert "workshop_download(['1'])" in out["hint"]
        by = {i["pfid"]: i for i in out["items"]}
        assert by["2"]["outdated"] is False

    def test_missing_remote_yields_none_not_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _settings(tmp_path)
        s.acf_path.parent.mkdir(parents=True)
        acf.save(s.acf_path, _acf_with("1", 100, "m1"))
        monkeypatch.setattr(webapi, "file_details", _remote({}, failed=["1"]))
        out = workshop.check_updates(s, None, include_steam_client=False)
        assert out["items"][0]["outdated"] is None
        assert out["lookup_failed"] == ["1"]

    def test_missing_local_timestamp_is_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _settings(tmp_path)
        s.acf_path.parent.mkdir(parents=True)
        acf.save(s.acf_path, _acf_with("1", 100, "m1"))
        data = acf.load(s.acf_path)
        acf.root(data)["WorkshopItemsInstalled"]["1"].pop("timeupdated")
        acf.save(s.acf_path, data)
        monkeypatch.setattr(
            webapi,
            "file_details",
            _remote({"1": {"title": "Unknown", "time_updated": 200, "unpublished": False}}),
        )
        out = workshop.check_updates(s, None, include_steam_client=False)
        assert out["items"][0]["outdated"] is None

    def test_nothing_installed(self, tmp_path: Path) -> None:
        out = workshop.check_updates(_settings(tmp_path), None, include_steam_client=False)
        assert out["items"] == [] and "hint" in out


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


def _search(s: Settings, query: str, **kw: Any) -> dict[str, Any]:
    args = {
        "limit": 5,
        "game_version": "1.6",
        "include_translations": False,
        "include_scenarios": False,
        "sort": "relevance",
        "days": 90,
    }
    args.update(kw)
    return workshop.search(s, query, **args)


class TestSearch:
    def test_no_key_returns_browse_url_with_filters(self, tmp_path: Path) -> None:
        out = _search(_settings(tmp_path), "harmony patch")
        assert out["results"] == []
        url = out["browse_url"]
        assert "searchtext=harmony%20patch" in url
        assert "requiredtags%5B%5D=Mod" in url and "requiredtags%5B%5D=1.6" in url
        assert "excludedtags%5B%5D=Translation" in url and "excludedtags%5B%5D=Scenario" in url
        assert out["filters"]["required_tags"] == ["Mod", "1.6"]

    def test_defaults_and_overrides_reach_the_api(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = Settings(**{**_settings(tmp_path).__dict__, "steam_web_api_key": "k"})
        seen: dict[str, Any] = {}

        def fake(q, k, n, required, excluded, sort, days, *_):
            seen.update(required=required, excluded=excluded, sort=sort, days=days)
            return {"query": q, "total": 1, "results": [{"title": q}]}

        monkeypatch.setattr(webapi, "search", fake)
        _search(s, "harmony")
        assert seen == {
            "required": ["Mod", "1.6"],
            "excluded": ["Translation", "Scenario"],
            "sort": "relevance",
            "days": 90,
        }
        _search(
            s,
            "",
            game_version="any",
            include_translations=True,
            include_scenarios=True,
            sort="trend",
            days=30,
        )
        assert seen == {"required": ["Mod"], "excluded": [], "sort": "trend", "days": 30}

    def test_relevance_needs_query_and_bad_sort_is_error(self, tmp_path: Path) -> None:
        s = Settings(**{**_settings(tmp_path).__dict__, "steam_web_api_key": "k"})
        assert "needs a query" in _search(s, "")["error"]
        assert "Unknown sort" in _search(s, "x", sort="bogus")["error"]

    def test_flags_ranked_nonmatch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Steam returns ~the whole Workshop for nonsense queries; the tool must say so."""
        s = Settings(**{**_settings(tmp_path).__dict__, "steam_web_api_key": "k"})
        monkeypatch.setattr(
            webapi,
            "search",
            lambda q, *a: {
                "query": q,
                "total": 38545,
                "results": [{"title": "Harmony"}, {"title": "HugsLib"}],
            },
        )
        assert "no match" in _search(s, "zzzqqq nonsense")["hint"]
        assert "hint" not in _search(s, "harmony")


class TestGameVersion:
    def test_major_minor_from_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.rimworld_tools import paths

        monkeypatch.setattr(
            paths, "discover", lambda _s: paths.RimWorldPaths(version="1.6.4871 rev590")
        )
        assert workshop.detected_game_version(_settings(tmp_path)) == "1.6"

    def test_fallback_when_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.rimworld_tools import paths

        monkeypatch.setattr(paths, "discover", lambda _s: paths.RimWorldPaths())
        assert workshop.detected_game_version(_settings(tmp_path)) == "1.6"
