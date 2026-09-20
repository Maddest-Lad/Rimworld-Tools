from __future__ import annotations

import gzip
import io
import json
import zipfile
from pathlib import Path

import pytest

from src.rimworld_tools import advisories, db
from src.rimworld_tools.config import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        steamcmd_prefix=tmp_path / "prefix",
        mods_dir=None,
        db_dir=tmp_path / "dbs",
        max_download_items=50,
        steam_web_api_key=None,
    )


def put(settings: Settings, name: str, filename: str, content: bytes | str, sub: str = "") -> Path:
    d = settings.db_dir / name / sub
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_bytes(content)
    return p


STEAM_DB = {
    "version": 1,
    "database": {
        "111": {
            "packageId": "Author.Alive",
            "steamName": "Alive Mod",
            "name": "alive about name",
            "gameVersions": ["1.5", "1.6"],
            "authors": "solo",
            "dependencies": {"222": ["Dep Legacy", "url"], "333": {"name": "Dep New", "url": "u"}},
            "unpublished": False,
        },
        "222": {"packageId": "author.dep", "name": "Dep Legacy", "gameVersions": "1.6"},
        "444": {
            "packageId": "author.bad",
            "steamName": "Bad Mod",
            "blacklist": {"value": True, "comment": "breaks saves"},
            "gameVersions": None,
        },
        "555": {"packageId": "author.gone", "steamName": "Gone", "unpublished": True},
        "294100": {"appid": True, "packageId": "ludeon.rimworld", "name": "RimWorld"},
    },
}

RULES = {
    "timestamp": 1,
    "rules": {
        "Author.Alive": {
            "loadAfter": {"Brrainz.Harmony": {"name": "Harmony", "comment": ["multi", "line"]}},
            "loadBefore": {"other.mod": {"name": "Other", "comment": "why"}},
            "loadTop": {"value": True, "comment": ""},
            "loadBottom": {"value": False},
        }
    },
}

UTI = {
    "version": "1",
    "rules": [
        {
            "oldWorkshopId": "555",
            "oldName": "Gone",
            "newWorkshopId": "999",
            "newName": "Gone Continued",
            "newPackageId": "Forker.Gone",
            "newVersions": ["1.5", "1.6"],
        },
        {"oldWorkshopId": "111", "newWorkshopId": "1111", "newName": "Alive Fork"},
        {"oldWorkshopId": "", "newWorkshopId": "1"},
    ],
}

NOVW = "<ModIdsToFix><li>Author.OldButFine</li><li>x.y</li></ModIdsToFix>"


class TestReaders:
    def test_steam_db_union_types_and_lowercasing(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        put(s, "steam_db", "steamDB.json", json.dumps(STEAM_DB))
        sdb = db.steam_db(s)
        assert sdb is not None
        e = sdb.by_pfid["111"]
        assert e.package_id == "author.alive"
        assert e.name == "Alive Mod"  # steamName preferred over name
        assert e.dependencies == {"222": "Dep Legacy", "333": "Dep New"}  # both encodings
        assert sdb.by_pfid["222"].game_versions == ["1.6"]  # bare string -> list
        assert sdb.by_pfid["444"].game_versions == []  # null -> []
        assert sdb.by_pfid["444"].blacklist_comment == "breaks saves"
        assert sdb.by_pfid["294100"].is_dlc
        assert sdb.pfid_by_package_id["author.gone"] == "555"
        assert sdb.name_for("AUTHOR.ALIVE") == "Alive Mod"

    def test_rules_lowercased_with_comment_shapes(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        put(s, "community_rules", "communityRules.json", json.dumps(RULES))
        rules = db.community_rules(s)
        assert rules is not None
        r = rules["author.alive"]
        assert r.load_after == {"brrainz.harmony"}
        assert r.load_before == {"other.mod"}
        assert r.load_top is True and r.load_bottom is False
        assert r.comments == {"brrainz.harmony": "multi line", "other.mod": "why"}

    def test_user_rules_seeded(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        assert db.user_rules(s) == {}
        assert json.loads((s.db_dir / "userRules.json").read_text()) == {
            "timestamp": 0,
            "rules": {},
        }

    @pytest.mark.parametrize("gz", [True, False])
    def test_use_this_instead_list_indexed_by_old_pfid(self, tmp_path: Path, gz: bool) -> None:
        s = _settings(tmp_path)
        body = json.dumps(UTI).encode("utf-8")
        put(
            s,
            "use_this_instead",
            "replacements.json.gz" if gz else "replacements.json",
            gzip.compress(body) if gz else body,
        )
        uti = db.use_this_instead(s)
        assert uti is not None
        assert set(uti) == {"555", "111"}  # blank oldWorkshopId dropped
        assert uti["555"].new_package_id == "forker.gone"
        assert uti["555"].new_versions == ["1.5", "1.6"]

    def test_no_version_warning_uses_only_the_matching_version_dir(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        put(s, "no_version_warning", "ModIdsToFix.xml", NOVW)
        put(
            s,
            "no_version_warning",
            "ModIdsToFix.xml",
            "<ModIdsToFix><li>only.six</li></ModIdsToFix>",
            sub="1.6",
        )
        put(
            s,
            "no_version_warning",
            "ModIdsToFix.xml",
            "<ModIdsToFix><li>only.five</li></ModIdsToFix>",
            sub="1.5",
        )
        assert db.no_version_warning(s, "1.6") == {"only.six"}
        assert db.no_version_warning(s, "1.4") is None
        assert db.no_version_warning(s, None) is None

    def test_reader_cache_keeps_other_loaded_databases(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _settings(tmp_path)
        steam_path = put(s, "steam_db", "steamDB.json", json.dumps(STEAM_DB))
        rules_path = put(s, "community_rules", "communityRules.json", json.dumps(RULES))
        steam_loads = 0
        rules_loads = 0

        def load_steam(path: Path):
            nonlocal steam_loads
            steam_loads += 1
            return path.name

        def load_rules(path: Path):
            nonlocal rules_loads
            rules_loads += 1
            return path.name

        assert db._cached(steam_path, load_steam) == "steamDB.json"
        assert db._cached(rules_path, load_rules) == "communityRules.json"
        assert db._cached(steam_path, load_steam) == "steamDB.json"
        assert steam_loads == 1 and rules_loads == 1

    def test_missing_dbs_are_none(self, tmp_path: Path) -> None:
        s = _settings(tmp_path)
        assert db.steam_db(s) is None
        assert db.community_rules(s) is None
        assert db.use_this_instead(s) is None
        assert db.no_version_warning(s, "1.6") is None
        assert all(not v["present"] for v in db.status(s).values())


def _zip(files: dict[str, str], top: str = "Repo-main") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(f"{top}/{name}", content)
    return buf.getvalue()


class TestSync:
    def test_extract_unwraps_and_swaps(self, tmp_path: Path) -> None:
        dest = tmp_path / "steam_db"
        db._extract_swap(_zip({"steamDB.json": "1", "nested/other.txt": "x"}), dest)
        assert (dest / "steamDB.json").read_text() == "1"
        assert (dest / "nested" / "other.txt").exists()
        db._extract_swap(_zip({"steamDB.json": "2"}), dest)
        assert (dest / "steamDB.json").read_text() == "2"
        assert not (dest / "nested").exists()  # old tree fully replaced
        assert not dest.with_name("steam_db.bak").exists()

    def test_zip_slip_rejected(self, tmp_path: Path) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../evil.txt", "x")
        with pytest.raises(ValueError):
            db._extract_swap(buf.getvalue(), tmp_path / "dest")
        assert not (tmp_path / "evil.txt").exists()

    def test_sync_etag_unchanged_and_branch_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _settings(tmp_path)
        calls: list[tuple[str, str | None]] = []

        def fake_fetch(source: db.Source, etag: str | None) -> tuple[int, bytes, str | None, str]:
            calls.append((source.repo, etag))
            if etag == '"e1"':
                return 304, b"", None, source.branch
            if source.repo.startswith("emipa606"):
                return 200, _zip({source.filename: "<ModIdsToFix/>"}), '"e1"', "master"
            return 200, _zip({source.filename: "{}"}), '"e1"', source.branch

        monkeypatch.setattr(db, "_fetch", fake_fetch)
        first = db.sync(s, ["steam_db", "no_version_warning"], force=False)
        assert [r["status"] for r in first["results"]] == ["updated", "updated"]
        assert (s.db_dir / "userRules.json").is_file()
        second = db.sync(s, ["steam_db"], force=False)
        assert second["results"][0]["status"] == "unchanged"
        assert calls[-1][1] == '"e1"'  # ETag was sent
        forced = db.sync(s, ["steam_db"], force=True)
        assert forced["results"][0]["status"] == "updated"
        assert calls[-1][1] is None  # force skips the ETag

    def test_failed_fetch_leaves_old_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        s = _settings(tmp_path)
        put(s, "steam_db", "steamDB.json", "keep")
        monkeypatch.setattr(db, "_fetch", lambda src, etag: (500, b"", None, src.branch))
        out = db.sync(s, ["steam_db"], force=True)
        assert out["results"][0]["status"] == "error"
        assert (s.db_dir / "steam_db" / "steamDB.json").read_text() == "keep"

    def test_unknown_source(self, tmp_path: Path) -> None:
        assert "error" in db.sync(_settings(tmp_path), ["nope"], force=False)


class TestAdvisories:
    @pytest.fixture
    def ctx(self, tmp_path: Path) -> advisories.Context:
        s = _settings(tmp_path)
        put(s, "steam_db", "steamDB.json", json.dumps(STEAM_DB))
        put(s, "use_this_instead", "replacements.json", json.dumps(UTI))
        put(s, "no_version_warning", "ModIdsToFix.xml", NOVW, sub="1.6")
        return advisories.Context.load(s, "1.6")

    def test_version_mismatch_suppressed_by_novw(self, ctx: advisories.Context) -> None:
        assert ctx.version("author.oldbutfine", ["1.5"], False) is None
        a = ctx.version("author.stale", ["1.5"], False)
        assert a is not None and a.kind == "version_mismatch"
        assert ctx.version("author.stale", ["1.6"], True) is None
        assert ctx.version("author.stale", [], None) is None

    def test_unpublished_becomes_replaced_when_fork_known(self, ctx: advisories.Context) -> None:
        a = ctx.replacement("555", unpublished=True)
        assert a is not None and a.kind == "replaced" and a.severity == "warn"
        assert "Gone Continued" in a.message and "999" in a.message
        assert a.action == {"tool": "workshop_download", "pfids": ["999"]}
        bare = ctx.replacement("777", unpublished=True)
        assert bare is not None and bare.kind == "unpublished"
        superseded = ctx.replacement("111", unpublished=False)
        assert superseded is not None and superseded.severity == "info"
        assert ctx.replacement("222", unpublished=False) is None

    def test_steam_db_unpublished_flag_is_never_trusted(self, ctx: advisories.Context) -> None:
        """The DB marks 555 unpublished, but without a live API result that must not surface.
        (Live check on a real mod set: the DB flag was wrong 4 times out of 4.)"""
        out = advisories.for_mod(ctx, "author.gone", "555", [], None, None, [], set())
        assert [a["kind"] for a in out] == ["replaced"]  # curated UTI entry still applies
        assert out[0]["severity"] == "info" and out[0]["message"].startswith("Superseded")
        # A DB-only "unpublished" mod with no fork yields nothing at all.
        ctx.replacements = {}
        assert advisories.for_mod(ctx, "author.gone", "555", [], None, None, [], set()) == []
        # A live API verdict does surface.
        out = advisories.for_mod(ctx, "author.gone", "555", [], None, True, [], set())
        assert [a["kind"] for a in out] == ["unpublished"]

    def test_blacklist(self, ctx: advisories.Context) -> None:
        a = ctx.blacklist("444")
        assert a is not None and "breaks saves" in a.message
        assert ctx.blacklist("111") is None

    def test_missing_dependency_named_via_steam_db(self, ctx: advisories.Context) -> None:
        installed = {"author.alive"}
        a = ctx.missing_dependency("author.dep", None, None, [], installed)
        assert a is not None
        assert "'Dep Legacy'" in a.message and "222" in a.message
        assert a.action == {"tool": "workshop_download", "pfids": ["222"]}
        assert ctx.missing_dependency("author.dep", None, None, ["AUTHOR.ALIVE"], installed) is None
        unknown = ctx.missing_dependency("nobody.knows", None, None, [], installed)
        assert unknown is not None and unknown.action is None

    def test_missing_dbs_notice_once(self, tmp_path: Path) -> None:
        ctx = advisories.Context.load(_settings(tmp_path), "1.6")
        assert set(ctx.missing_dbs) == {"steam_db", "use_this_instead", "no_version_warning"}
        notice = ctx.db_notice()
        assert notice is not None and notice["action"] == {"tool": "db_sync"}
        # No per-mod advisories can be produced, but nothing errors.
        assert advisories.for_mod(ctx, "x", "1", ["1.5"], False, None, [], set()) == [
            {
                "kind": "version_mismatch",
                "severity": "warn",
                "message": "Declares ['1.5']; game is 1.6. May still work — check the Workshop page.",
            }
        ]
