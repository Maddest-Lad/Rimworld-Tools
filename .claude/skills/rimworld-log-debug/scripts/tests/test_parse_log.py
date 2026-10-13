from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import parse_log

FX = HERE / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def fixtures() -> None:
    sys.path.insert(0, str(HERE))
    import make_fixtures

    make_fixtures.main()  # cheap; keeps fixtures in step with the generator


def names(session: parse_log.Session) -> list[str]:
    return [s.name for s in session.signatures.values()]


def sig(session: parse_log.Session, name: str) -> parse_log.Signature:
    return next(s for s in session.signatures.values() if s.name == name)


def test_header_and_session_metadata() -> None:
    (s,) = parse_log.parse(FX / "catalogue.log")
    assert s.game_version == "1.7.4976 rev1043"
    assert s.meta["Started"].startswith("2026-10-12")
    assert "-quicktest" in s.meta["Command"]
    assert s.mods == ["ludeon.rimworld", "brrainz.harmony", "example.buggymod"]


def test_catalogue_classification() -> None:
    (s,) = parse_log.parse(FX / "catalogue.log")
    got = names(s)
    for expected in (
        "xml_unknown_field",
        "xref_unresolved",
        "type_not_found",
        "workshop_no_folder",
        "missing_method",
        "unity_stub",
        "assetbundle_unsupported",
        "native_missing",
        "prepatcher",
    ):
        assert expected in got, got
    # Info and engine chatter never reach the ranked signatures.
    assert "keybind_conflict" not in got and "engine_warning" not in got
    assert s.noise["keybind_conflict"] == 1
    assert s.noise["dependency_no_url"] == 1
    assert s.noise["engine_warning"] == 1
    # An INFO "Harmony patches applied" line is not an error; GPU/version INFO lines are ignored.
    assert "harmony_exception" not in got and "logged_warning" not in got
    # Every Prepatcher line collapses into one high-severity row.
    assert sig(s, "prepatcher").count == 2 and sig(s, "prepatcher").severity == "high"
    # First real error is the XML error, which comes first in the file.
    assert s.first_error is not None and s.first_error.name == "xml_unknown_field"


def test_attribution_sources() -> None:
    (s,) = parse_log.parse(FX / "catalogue.log")
    xml = sig(s, "xml_unknown_field")
    assert "source:Titan Vehicles Upgrades" in xml.mods
    assert "pfid:3484382302" in xml.mods
    assert "ns:OldMod" in sig(s, "missing_method").mods
    assert (
        "ns:FpsMod" in sig(s, "unity_stub").mods
    )  # caller from the captured logging stack
    assert "bundle:shinyshaders" in sig(s, "assetbundle_unsupported").mods
    assert "ns:NativeMod" in sig(s, "native_missing").mods


def test_tick_spam_dedupes_to_one_signature_with_patch_owner() -> None:
    start = time.perf_counter()
    (s,) = parse_log.parse(FX / "tick_spam.log")
    elapsed = time.perf_counter() - start
    ticks = [x for x in s.signatures.values() if x.name == "exception_ticking"]
    assert len(ticks) == 1 and ticks[0].count == 5000
    mods = ticks[0].mods
    assert "ns:BuggyMod" in mods
    assert "patch:other.tickmod" in mods  # HarmonyMod names the patch owner
    assert "harmony:Verse" in mods  # patched vanilla method is flagged, not blamed
    assert elapsed < 5.0


def test_two_sessions_split_on_header() -> None:
    sessions = parse_log.parse(FX / "two_sessions.log")
    assert len(sessions) == 2
    assert names(sessions[0]) == ["xml_unknown_field"]
    assert names(sessions[1]) == ["type_not_found"]


def test_unstamped_paste_groups_by_shape() -> None:
    (s,) = parse_log.parse(FX / "unstamped_paste.log")
    tick = sig(s, "exception_ticking")
    assert tick.count == 1 and "ns:BuggyMod" in tick.mods
    assert s.entries == 2


def test_grep_filters_entries() -> None:
    import re

    (s,) = parse_log.parse(FX / "catalogue.log", grep=re.compile("cross-reference"))
    assert names(s) == ["xref_unresolved"]


def test_ranked_mod_filter_and_json() -> None:
    (s,) = parse_log.parse(FX / "catalogue.log")
    only = parse_log.ranked(s, 10, "titan")
    assert [x.name for x in only] == ["xml_unknown_field"]
    d = parse_log.to_dict(s, 3, None)
    json.dumps(d)  # serialisable
    assert d["game_version"] == "1.7.4976 rev1043" and len(d["top"]) == 3


def test_mod_index_maps_namespace_and_harmony_id(tmp_path: Path) -> None:
    mods = {
        "mods": [
            {
                "package_id": "old.oldmod",
                "name": "Old Mod",
                "assemblies": ["OldMod.dll"],
            },
            {"package_id": "other.tickmod", "name": "Tick Mod"},
        ]
    }
    p = tmp_path / "mods.json"
    p.write_text(json.dumps(mods), encoding="utf-8")
    index = parse_log.load_mod_index(p)
    (s,) = parse_log.parse(FX / "catalogue.log", index)
    assert "ns:old.oldmod" in sig(s, "missing_method").mods
    (t,) = parse_log.parse(FX / "tick_spam.log", index)
    assert "patch:other.tickmod" in sig(t, "exception_ticking").mods


def test_real_excerpt_if_present() -> None:
    path = FX / "real_excerpt.log"
    if not path.exists():
        pytest.skip("no real log excerpt on this machine")
    sessions = parse_log.parse(path)
    if not sessions[0].meta:
        pytest.skip(
            "links/logs/Player.log has no 1.7 header (old log or links/logs not updated)"
        )
    assert sessions[0].game_version.startswith("1.7")
    assert sessions[0].meta.get("Runtime", "").startswith(".NET")


def test_cli_markdown(capsys) -> None:
    assert parse_log.main([str(FX / "catalogue.log"), "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "First real error" in out and "xml_unknown_field" in out
    assert "RimWorld 1.7.4976 rev1043" in out
