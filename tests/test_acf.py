from __future__ import annotations

from pathlib import Path

import pytest

from src.rimworld_tools import acf

SAMPLE = """"AppWorkshop"
{
\t"appid"\t\t"294100"
\t"SizeOnDisk"\t\t"1234"
\t"WorkshopItemsInstalled"
\t{
\t\t"111"
\t\t{
\t\t\t"size"\t\t"100"
\t\t\t"timeupdated"\t\t"1700000000"
\t\t\t"manifest"\t\t"5555"
\t\t}
\t\t"222"
\t\t{
\t\t\t"size"\t\t"garbage"
\t\t\t"timeupdated"\t\t""
\t\t\t"manifest"\t\t"6666"
\t\t}
\t}
\t"WorkshopItemDetails"
\t{
\t\t"111"
\t\t{
\t\t\t"manifest"\t\t"5555"
\t\t\t"timeupdated"\t\t"1700000000"
\t\t\t"timetouched"\t\t"1700000001"
\t\t}
\t\t"333"
\t\t{
\t\t\t"manifest"\t\t"7777"
\t\t\t"timeupdated"\t\t"1600000000"
\t\t}
\t}
}
"""


@pytest.fixture
def acf_file(tmp_path: Path) -> Path:
    p = tmp_path / "appworkshop_294100.acf"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


class TestRead:
    def test_merges_sections_installed_wins(self, acf_file: Path) -> None:
        items = acf.items(acf.load(acf_file))
        assert set(items) == {"111", "222", "333"}
        assert items["111"].size == 100
        assert items["333"].size is None  # details-only entry

    def test_garbage_values_yield_none_not_exceptions(self, acf_file: Path) -> None:
        items = acf.items(acf.load(acf_file))
        assert items["222"].size is None
        assert items["222"].timeupdated is None

    def test_missing_file_yields_skeleton(self, tmp_path: Path) -> None:
        data = acf.load(tmp_path / "nope.acf")
        assert acf.items(data) == {}


class TestRemove:
    def test_removes_from_both_sections_and_returns_manifests(self, acf_file: Path) -> None:
        data = acf.load(acf_file)
        manifests = acf.remove_items(data, ["111", "333", "404"])
        assert manifests == {"111": {"5555"}, "333": {"7777"}, "404": set()}
        assert set(acf.items(data)) == {"222"}


class TestOrphans:
    def test_detects_entries_missing_on_disk(self, acf_file: Path, tmp_path: Path) -> None:
        content = tmp_path / "content"
        (content / "111").mkdir(parents=True)
        (content / "notanumber").mkdir()
        data = acf.load(acf_file)
        assert acf.orphans(data, content) == ["222", "333"]

    def test_dry_run_does_not_write(self, acf_file: Path, tmp_path: Path) -> None:
        before = acf_file.read_text(encoding="utf-8")
        out = acf.repair(acf_file, tmp_path / "content", dry_run=True)
        assert out["orphans"] == ["111", "222", "333"]
        assert out["removed"] is False
        assert acf_file.read_text(encoding="utf-8") == before

    def test_repair_writes_with_backup(
        self, acf_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(acf, "steam_processes_running", lambda *_: [])
        content = tmp_path / "content"
        (content / "111").mkdir(parents=True)
        out = acf.repair(acf_file, content, dry_run=False)
        assert out["removed"] is True
        assert Path(out["backup_path"]).is_file()
        assert set(acf.items(acf.load(acf_file))) == {"111"}

    def test_refuses_while_steam_running(
        self, acf_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(acf, "steam_processes_running", lambda *_: ["steamcmd.exe"])
        out = acf.repair(acf_file, tmp_path / "content", dry_run=False)
        assert "Refusing" in out["error"]
        assert out["removed"] is False


class TestSave:
    def test_round_trip_preserves_shape(self, acf_file: Path) -> None:
        data = acf.load(acf_file)
        acf.save(acf_file, data)
        again = acf.load(acf_file)
        assert acf.items(again) == acf.items(data)
        assert acf_file.with_suffix(".acf.backup").is_file()

    def test_restores_backup_on_write_failure(
        self, acf_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = acf_file.read_text(encoding="utf-8")
        data = acf.load(acf_file)

        def boom(self: Path, *a: object, **k: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", boom)
        with pytest.raises(OSError):
            acf.save(acf_file, data)
        monkeypatch.undo()
        assert acf_file.read_text(encoding="utf-8") == original
