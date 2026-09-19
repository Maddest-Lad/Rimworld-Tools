from __future__ import annotations

from pathlib import Path

import pytest

from src.rimworld_tools import paths


def make_game_dir(root: Path, version: str = "1.6.4871 rev573") -> Path:
    game = root / "steamapps" / "common" / "RimWorld"
    game.mkdir(parents=True)
    (game / "Version.txt").write_text(version, encoding="utf-8")
    (game / "Mods").mkdir()
    return game


def write_libraryfolders(
    steam_root: Path, libraries: list[Path], app_in: Path | None = None
) -> None:
    """Emit a realistic multi-line libraryfolders.vdf. app_in defaults to the first library."""
    if app_in is None and libraries:
        app_in = libraries[0]
    blocks = []
    for i, lib in enumerate(libraries):
        apps = '\t\t\t"294100"\t\t"12345"\n' if lib == app_in else ""
        blocks.append(
            f'\t"{i}"\n'
            "\t{\n"
            f'\t\t"path"\t\t"{lib.as_posix()}"\n'
            '\t\t"apps"\n'
            "\t\t{\n"
            f"{apps}"
            "\t\t}\n"
            "\t}\n"
        )
    (steam_root / "config").mkdir(parents=True, exist_ok=True)
    (steam_root / "config" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n' + "".join(blocks) + "}\n", encoding="utf-8"
    )


class TestVersionAndValidation:
    def test_reads_version(self, tmp_path: Path) -> None:
        make_game_dir(tmp_path)
        assert paths.read_version(tmp_path / "steamapps/common/RimWorld") == "1.6.4871 rev573"

    def test_rejects_malformed_version(self, tmp_path: Path) -> None:
        game = tmp_path / "game"
        game.mkdir()
        (game / "Version.txt").write_text("not a version", encoding="utf-8")
        assert paths.read_version(game) is None
        assert not paths.is_rimworld_dir(game)

    def test_validates_by_executable_when_version_missing(self, tmp_path: Path) -> None:
        game = tmp_path / "game"
        game.mkdir()
        (game / "RimWorldWin64.exe").write_text("", encoding="utf-8")
        assert paths.is_rimworld_dir(game)

    def test_name_alone_is_not_enough(self, tmp_path: Path) -> None:
        """A look-alike directory must never be accepted on its name."""
        impostor = tmp_path / "RimWorld"
        impostor.mkdir()
        assert not paths.is_rimworld_dir(impostor)


class TestSteamDiscovery:
    def test_finds_rimworld_via_libraryfolders(self, tmp_path: Path) -> None:
        steam = tmp_path / "Steam"
        steam.mkdir()
        make_game_dir(steam)
        write_libraryfolders(steam, [steam])
        found = paths.find_rimworld_in_steam(steam)
        assert found is not None
        assert "libraryfolders.vdf" in found.provenance

    def test_finds_rimworld_in_secondary_library(self, tmp_path: Path) -> None:
        steam = tmp_path / "Steam"
        (steam / "steamapps").mkdir(parents=True)
        other = tmp_path / "D_Games"
        other.mkdir()
        make_game_dir(other)
        write_libraryfolders(steam, [steam, other], app_in=other)
        found = paths.find_rimworld_in_steam(steam)
        assert found is not None
        assert Path(found.path) == other / "steamapps/common/RimWorld"

    def test_returns_none_when_absent(self, tmp_path: Path) -> None:
        steam = tmp_path / "Steam"
        (steam / "steamapps").mkdir(parents=True)
        write_libraryfolders(steam, [steam])
        assert paths.find_rimworld_in_steam(steam) is None

    def test_survives_corrupt_vdf(self, tmp_path: Path) -> None:
        steam = tmp_path / "Steam"
        (steam / "config").mkdir(parents=True)
        (steam / "config" / "libraryfolders.vdf").write_text("{{{ not vdf", encoding="utf-8")
        make_game_dir(steam)
        found = paths.find_rimworld_in_steam(steam)
        assert found is not None  # falls back to the layout check


class TestWorkshopDerivation:
    def test_derives_workshop_dir(self, tmp_path: Path) -> None:
        game = make_game_dir(tmp_path)
        workshop = tmp_path / "steamapps" / "workshop" / "content" / "294100"
        workshop.mkdir(parents=True)
        found = paths._workshop_dir_for(game)
        assert found is not None and Path(found.path) == workshop

    def test_none_without_common_segment(self, tmp_path: Path) -> None:
        assert paths._workshop_dir_for(tmp_path / "elsewhere" / "RimWorld") is None


class TestDiscover:
    def test_mods_dir_override_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RIMWORLD_TOOLS_MODS_DIR", str(tmp_path / "MyMods"))
        monkeypatch.setattr(paths, "find_steam_root", lambda: None)
        result = paths.discover()
        assert result.mods_dir is not None
        assert result.mods_dir.provenance == "RIMWORLD_TOOLS_MODS_DIR"

    def test_reports_nothing_found_cleanly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RIMWORLD_TOOLS_MODS_DIR", raising=False)
        monkeypatch.setattr(paths, "find_steam_root", lambda: None)
        monkeypatch.setattr(paths, "find_config_dir", lambda: None)
        result = paths.discover()
        assert result.game_dir is None and result.version is None
        assert result.to_dict()["game_dir"] is None
