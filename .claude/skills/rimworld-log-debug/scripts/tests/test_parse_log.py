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
    if not (FX / "catalogue.log").exists():
        sys.path.insert(0, str(HERE))
        import make_fixtures

        make_fixtures.main()


def names(session: parse_log.Session) -> list[str]:
    return [s.name for s in session.signatures.values()]


def test_catalogue_classification() -> None:
    (s,) = parse_log.parse(FX / "catalogue.log")
    assert s.mods == ["ludeon.rimworld", "brrainz.harmony", "example.buggymod"]
    got = names(s)
    for expected in (
        "xml_unknown_field",
        "xref_unresolved",
        "type_not_found",
        "workshop_no_folder",
        "missing_method",
    ):
        assert expected in got, got
    # Info and noise never reach the ranked signatures.
    assert "keybind_conflict" not in got and "thread_abort" not in got
    assert s.noise["keybind_conflict"] == 1
    assert s.noise["thread_abort"] == 1
    assert s.noise["dependency_no_url"] == 1
    # "Harmony patches applied" is not an error.
    assert "harmony_exception" not in got
    # First real error is the XML error, which comes first in the file.
    assert s.first_error is not None and s.first_error.name == "xml_unknown_field"


def test_attribution_from_source_and_file_lines() -> None:
    (s,) = parse_log.parse(FX / "catalogue.log")
    xml = next(sig for sig in s.signatures.values() if sig.name == "xml_unknown_field")
    assert "source:Titan Vehicles Upgrades" in xml.mods
    assert "pfid:3484382302" in xml.mods
    window = next(sig for sig in s.signatures.values() if sig.name == "missing_method")
    assert "ns:OldMod" in window.mods


def test_tick_spam_dedupes_to_one_signature() -> None:
    start = time.perf_counter()
    (s,) = parse_log.parse(FX / "tick_spam.log")
    elapsed = time.perf_counter() - start
    ticks = [sig for sig in s.signatures.values() if sig.name == "exception_ticking"]
    assert len(ticks) == 1
    assert ticks[0].count == 5000
    assert "ns:BuggyMod" in ticks[0].mods
    assert (
        "harmony:Verse" in ticks[0].mods
    )  # patched vanilla method is flagged, not blamed
    assert elapsed < 2.0


def test_fallback_noise_is_bucketed_not_listed() -> None:
    (s,) = parse_log.parse(FX / "fallback_noise.log")
    assert s.noise["fallback_dll"] == 1000
    assert not s.signatures


def test_two_sessions_split_on_mono_header() -> None:
    sessions = parse_log.parse(FX / "two_sessions.log")
    assert len(sessions) == 2
    assert names(sessions[0]) == ["xml_unknown_field"]
    assert names(sessions[1]) == ["type_not_found"]
    assert sessions[1].mods == ["ludeon.rimworld"]


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
    assert d["mod_count"] == 3 and len(d["top"]) == 3


def test_mod_index_maps_namespace_to_package_id(tmp_path: Path) -> None:
    mods = {
        "mods": [
            {
                "package_id": "old.oldmod",
                "name": "Old Mod",
                "assemblies": ["OldMod.dll"],
            }
        ]
    }
    p = tmp_path / "mods.json"
    p.write_text(json.dumps(mods), encoding="utf-8")
    index = parse_log.load_mod_index(p)
    (s,) = parse_log.parse(FX / "catalogue.log", index)
    window = next(sig for sig in s.signatures.values() if sig.name == "missing_method")
    assert "ns:old.oldmod" in window.mods


def test_real_excerpt_if_present() -> None:
    path = FX / "real_excerpt.log"
    if not path.exists():
        pytest.skip("no real log excerpt on this machine")
    sessions = parse_log.parse(path)
    assert sessions[0].noise["fallback_dll"] > 50
    assert "xml_unknown_field" in names(sessions[0])


def test_cli_markdown(capsys) -> None:
    assert parse_log.main([str(FX / "catalogue.log"), "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "First real error" in out and "xml_unknown_field" in out
