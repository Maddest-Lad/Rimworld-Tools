from __future__ import annotations

import _winapi
from pathlib import Path

import pytest

from src.rimworld_tools import filesystem


@pytest.fixture
def target(tmp_path: Path) -> Path:
    t = tmp_path / "Mods"
    t.mkdir()
    (t / "marker.txt").write_text("x", encoding="utf-8")
    return t


class TestRmtree:
    def test_removes_read_only_files(self, tmp_path: Path) -> None:
        d = tmp_path / "mod"
        d.mkdir()
        f = d / "ro.txt"
        f.write_text("x", encoding="utf-8")
        f.chmod(0o444)
        filesystem.rmtree(d)
        assert not d.exists()

    def test_rmtree_on_junction_does_not_delete_target(self, tmp_path: Path, target: Path) -> None:
        """A junction must be unlinked, never recursed into."""
        link = tmp_path / "link"
        _winapi.CreateJunction(str(target), str(link))
        try:
            filesystem.rmtree(link)
        except OSError:
            pass  # shutil refuses to rmtree a reparse point; that's acceptable
        assert (target / "marker.txt").exists()

    def test_long_path_does_not_resolve_junctions(self, tmp_path: Path, target: Path) -> None:
        link = tmp_path / "link"
        _winapi.CreateJunction(str(target), str(link))
        assert filesystem.long_path(link).endswith("\\link")
