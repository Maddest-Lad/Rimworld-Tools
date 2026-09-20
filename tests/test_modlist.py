from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.rimworld_tools import modlist, paths
from src.rimworld_tools.config import Settings

MODS_CONFIG = """﻿<?xml version="1.0" encoding="utf-8"?>
<ModsConfigData>
  <version>1.6.4871 rev590</version>
  <activeMods>
    <li>ludeon.rimworld</li>
    <li>author.dup_steam</li>
    <li>Author.Local</li>
    <li>ghost.notinstalled</li>
  </activeMods>
  <knownExpansions>
    <li>ludeon.rimworld.royalty</li>
  </knownExpansions>
</ModsConfigData>
"""


def about_xml(pid: str, extra: str = "") -> str:
    return f"<ModMetaData><packageId>{pid}</packageId><name>{pid}</name>{extra}</ModMetaData>"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    game = tmp_path / "RimWorld"
    data, modsd, ws, cfg = (
        game / "Data",
        game / "Mods",
        tmp_path / "ws" / "294100",
        tmp_path / "Config",
    )
    for p in (data, modsd, ws, cfg):
        p.mkdir(parents=True)
    (cfg / "ModsConfig.xml").write_text(MODS_CONFIG, encoding="utf-8")
    (tmp_path / "dbs" / "community_rules").mkdir(parents=True)
    (tmp_path / "dbs" / "community_rules" / "communityRules.json").write_text(
        '{"rules": {}}', encoding="utf-8"
    )

    def mk(root: Path, folder: str, pid: str, extra: str = "") -> None:
        (root / folder / "About").mkdir(parents=True)
        (root / folder / "About" / "About.xml").write_text(about_xml(pid, extra), "utf-8")

    mk(data, "Core", "Ludeon.RimWorld")
    mk(modsd, "DupLocal", "author.dup", "<loadAfter><li>author.local</li></loadAfter>")
    mk(ws, "111", "author.dup")
    mk(modsd, "Local", "author.local", "<loadAfter><li>author.dup</li></loadAfter>")
    monkeypatch.setattr(
        paths,
        "discover",
        lambda _s: paths.RimWorldPaths(
            game_dir=paths.Found(str(game), "t"),
            mods_dir=paths.Found(str(modsd), "t"),
            workshop_dir=paths.Found(str(ws), "t"),
            config_dir=paths.Found(str(cfg), "t"),
            version="1.6.4871 rev590",
        ),
    )
    monkeypatch.setattr(paths, "find_steam_root", lambda: None)
    return Settings(
        steamcmd_prefix=tmp_path / "prefix",
        mods_dir=None,
        db_dir=tmp_path / "dbs",
        max_download_items=50,
        steam_web_api_key=None,
    )


class TestModsConfig:
    def test_round_trip_preserves_suffix_and_expansions(self, tmp_path: Path) -> None:
        p = tmp_path / "ModsConfig.xml"
        p.write_text(MODS_CONFIG, encoding="utf-8")
        cfg = modlist.read_mods_config(p)
        assert cfg.version == "1.6.4871 rev590"
        assert cfg.active == [
            "ludeon.rimworld",
            "author.dup_steam",
            "Author.Local",
            "ghost.notinstalled",
        ]
        assert cfg.active_ids == [
            "ludeon.rimworld",
            "author.dup",
            "author.local",
            "ghost.notinstalled",
        ]
        backup = modlist.write_mods_config(p, cfg)
        assert backup is not None and backup.is_file()
        again = modlist.read_mods_config(p)
        assert again.active == cfg.active and again.known_expansions == ["ludeon.rimworld.royalty"]
        assert p.read_text(encoding="utf-8").startswith('<?xml version="1.0" encoding="utf-8"?>')

    def test_write_preserves_unknown_root_fields(self, tmp_path: Path) -> None:
        p = tmp_path / "ModsConfig.xml"
        p.write_text(
            "<ModsConfigData><version>1.6</version><customFlag>keep</customFlag>"
            "<activeMods /><knownExpansions /></ModsConfigData>",
            encoding="utf-8",
        )
        modlist.write_mods_config(p, modlist.ModsConfig("1.6", ["core"], []))
        root = ET.fromstring(p.read_text())
        assert root.findtext("customFlag") == "keep"


class TestPrepare:
    def test_resolves_duplicates_by_suffix_and_reports_unresolved(self, world: Settings) -> None:
        prep = modlist.prepare(world)
        assert not isinstance(prep, dict)
        assert (
            prep.resolved["author.dup"].source == "steam"
        )  # _steam suffix picked the Workshop copy
        assert prep.unresolved == ["ghost.notinstalled"]
        assert prep.names["ludeon.rimworld"] == "Ludeon.RimWorld"

    def test_rules_come_from_the_selected_copy(self, world: Settings) -> None:
        out = modlist.sort_modlist(world)
        assert out["ok"]
        ids = [item["package_id"] for item in out["order"]]
        assert ids.index("author.dup") < ids.index("author.local")

    def test_duplicate_active_ids_are_reported(self, world: Settings) -> None:
        path = modlist.config_path(world)
        assert path is not None
        cfg = modlist.read_mods_config(path)
        cfg.active.append("AUTHOR.LOCAL")
        modlist.write_mods_config(path, cfg)
        out = modlist.sort_modlist(world)
        assert out["duplicate_active"] == ["AUTHOR.LOCAL"]


class TestSortModlist:
    def test_write_refuses_without_community_rules(self, world: Settings) -> None:
        import shutil

        shutil.rmtree(world.db_dir / "community_rules")
        out = modlist.sort_modlist(world, dry_run=False)
        assert "unavailable" in out["error"]

    def test_write_refuses_while_rimworld_is_running(
        self, world: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.rimworld_tools import acf

        monkeypatch.setattr(acf, "steam_processes_running", lambda _: ["rimworldwin64.exe"])
        out = modlist.sort_modlist(world, dry_run=False)
        assert "while rimworldwin64.exe is running" in out["error"]

    def test_dry_run_orders_without_writing(self, world: Settings) -> None:
        before = modlist.config_path(world).read_text(encoding="utf-8")  # type: ignore[union-attr]
        out = modlist.sort_modlist(world, dry_run=True)
        assert out["ok"] is True
        ids = [o["package_id"] for o in out["order"]]
        assert ids == ["ludeon.rimworld", "author.dup", "author.local"]
        assert out["unresolved"] == ["ghost.notinstalled"]
        assert "written" not in out
        assert modlist.config_path(world).read_text(encoding="utf-8") == before  # type: ignore[union-attr]

    def test_write_snapshots_then_keeps_suffix_and_unresolved(self, world: Settings) -> None:
        # Reverse the current order so a write actually happens.
        p = modlist.config_path(world)
        assert p is not None
        cfg = modlist.read_mods_config(p)
        cfg.active = list(reversed(cfg.active))
        modlist.write_mods_config(p, cfg)
        out = modlist.sort_modlist(world, dry_run=False)
        assert out["ok"] and out["written"] == str(p)
        assert out["snapshot_before"]
        written = modlist.read_mods_config(p)
        assert written.active == [
            "ludeon.rimworld",
            "author.dup_steam",
            "Author.Local",
            "ghost.notinstalled",
        ]
        assert written.known_expansions == ["ludeon.rimworld.royalty"]
        snaps = modlist.list_snapshots(world)
        assert len(snaps) == 1 and "before sort" in snaps[0]["note"]

    def test_no_op_when_already_sorted(self, world: Settings) -> None:
        out = modlist.sort_modlist(world, dry_run=False)
        assert out["ok"] and out["changed_positions"] == 0 and "written" not in out

    def test_refuses_to_overwrite_a_changed_config(
        self, world: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prep = modlist.prepare(world)
        assert not isinstance(prep, dict)
        path = prep.path
        prep.cfg.active = list(reversed(prep.cfg.active))
        cfg = modlist.read_mods_config(path)
        modlist.write_mods_config(path, cfg)
        monkeypatch.setattr(modlist, "prepare", lambda _: prep)
        out = modlist.sort_modlist(world, dry_run=False)
        assert "changed while" in out["error"]
        assert "written" not in out

    def test_cycle_writes_nothing_and_names_sources(self, world: Settings) -> None:
        (world.db_dir).mkdir(parents=True, exist_ok=True)
        (world.db_dir / "userRules.json").write_text(
            json.dumps(
                {"timestamp": 1, "rules": {"author.dup": {"loadAfter": {"author.local": {}}}}}
            ),
            "utf-8",
        )
        p = modlist.config_path(world)
        before = p.read_text(encoding="utf-8")  # type: ignore[union-attr]
        out = modlist.sort_modlist(world, dry_run=False)
        assert out["ok"] is False and out["failed_tier"] == "tier2"
        rules = {e["rule"]: e["sources"] for e in out["cycles"][0]["edges"]}
        assert rules == {
            "author.local after author.dup": ["about:author.local"],
            "author.dup after author.local": ["user"],
        }
        assert p.read_text(encoding="utf-8") == before  # type: ignore[union-attr]
        assert "cycles" in modlist.diagnose(world) and modlist.diagnose(world)["ok"] is False

    def test_dependency_issues_bucketed(self, world: Settings) -> None:
        d = Path(modlist.prepare(world).resolved["author.local"].path)  # type: ignore[union-attr]
        (d / "About" / "About.xml").write_text(
            about_xml(
                "author.local",
                "<modDependencies><li><packageId>author.inactive</packageId><displayName>Inactive</displayName></li>"
                "<li><packageId>author.absent</packageId><steamWorkshopUrl>steam://url/CommunityFilePage/777</steamWorkshopUrl></li></modDependencies>",
            ),
            "utf-8",
        )
        mods_dir = d.parent
        (mods_dir / "Inactive" / "About").mkdir(parents=True)
        (mods_dir / "Inactive" / "About" / "About.xml").write_text(
            about_xml("author.inactive"), "utf-8"
        )
        out = modlist.sort_modlist(world)
        by = {i["package_id"]: i for i in out["dependency_issues"]}
        assert by["author.inactive"]["status"] == "installed_but_inactive"
        assert by["author.absent"]["status"] == "not_installed"
        assert by["author.absent"]["action"] == {"tool": "workshop_subscribe", "pfids": ["777"]}


class TestSnapshotsAndDiff:
    def test_snapshot_and_diff(self, world: Settings) -> None:
        snap = modlist.snapshot(world, "baseline")
        assert snap["count"] == 4
        p = modlist.config_path(world)
        assert p is not None
        cfg = modlist.read_mods_config(p)
        cfg.active = [
            "Author.Local",
            "ludeon.rimworld",
            "new.mod",
        ]  # dropped two, moved one, added one
        modlist.write_mods_config(p, cfg)
        out = modlist.diff(world, "latest", "current")
        assert out["added"] == ["new.mod"]
        assert out["removed"] == ["author.dup_steam", "ghost.notinstalled"]
        assert {m["id"] for m in out["moved"]} == {"ludeon.rimworld", "Author.Local"}
        assert modlist.diff(world, snap["id"], "current")["added"] == ["new.mod"]
        assert modlist.diff(world, "current", "current")["moved"] == []

    def test_bad_ref_lists_snapshots(self, world: Settings) -> None:
        out = modlist.diff(world, "nope", "current")
        assert "error" in out and "snapshots" in out

    def test_snapshots_do_not_collide_within_one_second(self, world: Settings) -> None:
        first = modlist.snapshot(world, "one")
        second = modlist.snapshot(world, "two")
        assert first["id"] != second["id"]
        assert len(modlist.list_snapshots(world)) == 2

    def test_snapshot_reference_cannot_escape_its_store(self, world: Settings) -> None:
        out = modlist.diff(world, "../outside", "current")
        assert "error" in out
