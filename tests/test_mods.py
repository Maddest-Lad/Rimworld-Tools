from __future__ import annotations

from pathlib import Path

import pytest

from src.rimworld_tools import mods
from src.rimworld_tools.config import Settings

GOOD = """﻿<?xml version="1.0" encoding="utf-8"?>
<ModMetaData>
  <name>Harmony</name>
  <author>Andreas Pardeike, Someone Else</author>
  <authors><li>Third</li></authors>
  <packageId>Brrainz.Harmony</packageId>
  <supportedVersions><li>1.4</li><li>1.5.1234</li><li>v1.6</li><li>garbage</li></supportedVersions>
  <modVersion>2.3.6</modVersion>
  <modDependencies>
    <li>
      <packageId>Zetrith.Prepatcher</packageId>
      <displayName>Prepatcher</displayName>
      <steamWorkshopUrl>steam://url/CommunityFilePage/2934420800</steamWorkshopUrl>
      <alternativePackageIds><li>jikulopo.prepatcher</li></alternativePackageIds>
    </li>
    <li isNull="True" />
  </modDependencies>
  <loadAfter><li>Ludeon.RimWorld</li></loadAfter>
  <forceLoadBefore><li>Some.Mod</li></forceLoadBefore>
  <incompatibleWith>Other.Mod</incompatibleWith>
</ModMetaData>
"""

MALFORMED = """<ModMetaData>
  <name>Broken & Co</name>
  <packageId>me.broken</packageId>
  <description>Unescaped < angle and & ampersand</description>
  <supportedVersions><li>1.6</li></supportedVersions>
</ModMetaData>
"""

VERSIONED = """<modMetaData>
  <packageId>me.versioned</packageId>
  <loadAfter><li>base.a</li></loadAfter>
  <loadAfterByVersion>
    <v1.6><li>six.a</li></v1.6>
    <v1.5><li>five.a</li></v1.5>
  </loadAfterByVersion>
  <forceLoadAfter><li>always.a</li></forceLoadAfter>
  <modDependenciesByVersion>
    <v1.6></v1.6>
  </modDependenciesByVersion>
  <modDependencies><li><packageId>legacy.dep</packageId><workshopUrl>https://steamcommunity.com/sharedfiles/filedetails/?id=42</workshopUrl></li></modDependencies>
</modMetaData>
"""

DLC = """<ModMetaData>
  <packageId>Ludeon.RimWorld.Royalty</packageId>
  <supportedVersions><li>1.6</li></supportedVersions>
</ModMetaData>
"""


def mod_dir(
    root: Path,
    name: str,
    about: str | None,
    about_dir: str = "About",
    about_file: str = "About.xml",
) -> Path:
    d = root / name
    d.mkdir(parents=True)
    if about is not None:
        (d / about_dir).mkdir()
        (d / about_dir / about_file).write_text(about, encoding="utf-8")
    return d


class TestParse:
    def test_full_parse(self, tmp_path: Path) -> None:
        d = mod_dir(tmp_path, "harmony", GOOD)
        a = mods.parse_about(d / "About" / "About.xml", "1.6")
        assert a.package_id == "brrainz.harmony"
        assert a.name == "Harmony"
        assert a.authors == ["Andreas Pardeike", "Someone Else", "Third"]
        assert a.supported_versions == ["1.4", "1.5", "1.6"]  # normalised, garbage dropped
        assert a.mod_version == "2.3.6"
        assert len(a.dependencies) == 1  # isNull entry skipped
        dep = a.dependencies[0]
        assert dep.package_id == "zetrith.prepatcher"
        assert dep.pfid == "2934420800"
        assert dep.alternatives == ["jikulopo.prepatcher"]
        assert a.load_after == ["ludeon.rimworld"]
        assert a.load_before == ["some.mod"]
        assert a.incompatible_with == ["other.mod"]  # bare string, not <li>
        assert a.warnings == []

    def test_bare_ampersand_and_lt_are_repaired_without_losing_fields(self, tmp_path: Path) -> None:
        d = mod_dir(tmp_path, "broken", MALFORMED)
        a = mods.parse_about(d / "About" / "About.xml", "1.6")
        assert a.package_id == "me.broken"
        assert a.name == "Broken & Co"
        assert a.supported_versions == ["1.6"]  # field AFTER the stray '<' survives
        assert any("leniently" in w for w in a.warnings)

    def test_unclosed_tag_falls_through_to_soup(self, tmp_path: Path) -> None:
        d = mod_dir(
            tmp_path,
            "unclosed",
            "<ModMetaData><packageId>me.unclosed</packageId><name>X<supportedVersions><li>1.6</li>"
            "</supportedVersions></ModMetaData>",
        )
        a = mods.parse_about(d / "About" / "About.xml", "1.6")
        assert a.package_id == "me.unclosed"
        assert any("leniently" in w for w in a.warnings)

    def test_by_version_replaces_and_force_always_applies(self, tmp_path: Path) -> None:
        d = mod_dir(tmp_path, "v", VERSIONED)
        a = mods.parse_about(d / "About" / "About.xml", "1.6")
        assert a.load_after == ["six.a", "always.a"]  # base.a replaced, force appended
        assert a.dependencies == []  # empty v1.6 block means "none", not "fall back"
        a5 = mods.parse_about(d / "About" / "About.xml", "1.5")
        assert a5.load_after == ["five.a", "always.a"]
        a4 = mods.parse_about(d / "About" / "About.xml", "1.4")
        assert a4.load_after == ["base.a", "always.a"]
        assert a4.dependencies[0].pfid == "42"  # workshopUrl alias accepted

    def test_dlc_name_and_appid_backfill(self, tmp_path: Path) -> None:
        d = mod_dir(tmp_path, "Royalty", DLC)
        m = mods.load_mod(d, "ludeon", "1.6")
        assert m.name == "Royalty"
        assert m.about is not None and m.about.steam_app_id == 1149640

    def test_case_insensitive_about_path(self, tmp_path: Path) -> None:
        d = mod_dir(tmp_path, "odd", GOOD, about_dir="about", about_file="about.xml")
        m = mods.load_mod(d, "local", "1.6")
        assert m.package_id == "brrainz.harmony"
        assert any("casing" in w for w in m.about.warnings)  # type: ignore[union-attr]

    def test_missing_about_and_scenario(self, tmp_path: Path) -> None:
        junk = mod_dir(tmp_path, "junk", None)
        assert mods.load_mod(junk, "local", "1.6").warnings == ["no About/About.xml"]
        sc = mod_dir(tmp_path, "scen", None)
        (sc / "x.rsc").write_text("", encoding="utf-8")
        assert "scenario" in mods.load_mod(sc, "local", "1.6").warnings[0]


class TestClassify:
    def test_sources(self, tmp_path: Path) -> None:
        game = tmp_path / "RimWorld"
        data, modsd, ws = game / "Data", game / "Mods", tmp_path / "workshop" / "294100"
        for p in (data, modsd, ws):
            p.mkdir(parents=True)
        core = mod_dir(data, "Core", DLC)
        sub = mod_dir(ws, "123", GOOD)
        local = mod_dir(modsd, "MyMod", GOOD)
        git = mod_dir(modsd, "GitMod", GOOD)
        (git / ".git").mkdir()
        cmd = mod_dir(modsd, "2009463077", GOOD)
        (cmd / "About" / "PublishedFileId.txt").write_text("2009463077\n", encoding="utf-8")
        (cmd / ".git").mkdir()  # stray .git must not win over the pfid match
        moved = mod_dir(modsd, "HarmonyCopy", GOOD)
        (moved / "About" / "PublishedFileId.txt").write_text("2009463077", encoding="utf-8")

        c = lambda d: mods.classify(d, data, modsd, ws)
        assert c(core) == "ludeon"
        assert c(sub) == "steam"
        assert c(local) == "local"
        assert c(git) == "git"
        assert c(cmd) == "steamcmd"
        assert c(moved) == "steamcmd"
        assert c(tmp_path / "elsewhere") == "unknown"

    def test_pfid_recovery_order(self, tmp_path: Path) -> None:
        d = mod_dir(tmp_path, "555", GOOD)
        assert mods.recover_pfid(d) == "555"  # numeric folder name
        (d / "About" / "PublishedFileId.txt").write_text("﻿777 ", encoding="utf-8")
        assert mods.recover_pfid(d) == "777"  # file wins
        (d / "About" / "PublishedFileId.txt").write_text("0", encoding="utf-8")
        assert mods.recover_pfid(d) == "555"  # invalid file falls back
        assert mods.recover_pfid(mod_dir(tmp_path, "named", GOOD)) is None


class TestInventory:
    @pytest.fixture
    def world(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
        from src.rimworld_tools import paths

        game = tmp_path / "RimWorld"
        data, modsd, ws = game / "Data", game / "Mods", tmp_path / "workshop" / "294100"
        for p in (data, modsd, ws):
            p.mkdir(parents=True)
        mod_dir(data, "Core", DLC.replace("Ludeon.RimWorld.Royalty", "Ludeon.RimWorld"))
        mod_dir(modsd, "Local", GOOD)
        mod_dir(ws, "2009463077", GOOD)  # duplicate packageId
        mod_dir(modsd, "Old", GOOD.replace("<li>v1.6</li>", ""))
        mod_dir(modsd, "junk", None)
        monkeypatch.setattr(
            paths,
            "discover",
            lambda _s: paths.RimWorldPaths(
                game_dir=paths.Found(str(game), "t"),
                mods_dir=paths.Found(str(modsd), "t"),
                workshop_dir=paths.Found(str(ws), "t"),
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

    def test_compact_default(self, world: Settings) -> None:
        out = mods.inventory(world)
        assert out["count"] == 4
        assert out["by_source"] == {"ludeon": 1, "steam": 1, "local": 2}
        assert out["invalid_folders"] == 1
        rec = next(r for r in out["mods"] if r["name"] == "Harmony" and r["source"] == "steam")
        assert set(rec) == {"package_id", "name", "source", "pfid", "version_ok", "advisories"}
        # GOOD declares a Prepatcher dependency that this world doesn't have.
        assert rec["advisories"] == [
            {
                "kind": "missing_dependency",
                "severity": "warn",
                "message": "Requires 'Prepatcher' (pfid 2934420800), not installed.",
                "action": {"tool": "workshop_subscribe", "pfids": ["2934420800"]},
            }
        ]
        assert rec["pfid"] == "2009463077"
        assert out["duplicates"] == {
            "brrainz.harmony": sorted(out["duplicates"]["brrainz.harmony"])
        }
        assert len(out["duplicates"]["brrainz.harmony"]) == 3

    def test_version_mismatch_flagged(self, world: Settings) -> None:
        out = mods.inventory(world, detail=True)
        old = next(r for r in out["mods"] if r["path"].endswith("Old"))
        assert old["version_ok"] is False
        assert old["advisories"][0]["kind"] == "version_mismatch"
        assert out["notice"]["kind"] == "databases_missing"  # DBs not synced in this fixture
        assert out["mods_with_advisories"] >= 1
        core = next(r for r in out["mods"] if r["source"] == "ludeon")
        assert core["version_ok"] is True

    def test_filters(self, world: Settings) -> None:
        assert mods.inventory(world, source="ludeon")["count"] == 1
        out = mods.inventory(world, package_ids=["BRRAINZ.HARMONY", "nope.mod"])
        assert out["count"] == 3
        assert out["not_installed"] == ["nope.mod"]
        assert "error" in mods.inventory(world, source="bogus")

    def test_include_invalid(self, world: Settings) -> None:
        out = mods.inventory(world, include_invalid=True)
        assert out["count"] == 5
        junk = next(r for r in out["mods"] if r["name"] == "junk")
        assert junk["warnings"] == ["no About/About.xml"]
