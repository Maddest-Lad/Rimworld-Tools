from __future__ import annotations

from pathlib import Path

import pytest

from src.rimworld_tools import symlink


@pytest.fixture
def target(tmp_path: Path) -> Path:
    t = tmp_path / "Mods"
    t.mkdir()
    (t / "marker.txt").write_text("x", encoding="utf-8")
    return t


class TestEnsureJunction:
    def test_creates_and_is_idempotent(self, tmp_path: Path, target: Path) -> None:
        link = tmp_path / "steam" / "steamapps" / "workshop" / "content" / "294100"
        first = symlink.ensure_junction(link, target)
        assert first.created and first.error is None
        assert (link / "marker.txt").exists()
        assert symlink.read_junction(link) == target.resolve()
        second = symlink.ensure_junction(link, target)
        assert second.already_correct and not second.created

    def test_missing_target_is_error(self, tmp_path: Path) -> None:
        out = symlink.ensure_junction(tmp_path / "link", tmp_path / "nope")
        assert out.error and "does not exist" in out.error

    def test_refuses_non_empty_dir_without_force(self, tmp_path: Path, target: Path) -> None:
        link = tmp_path / "link"
        link.mkdir()
        (link / "old_mod").mkdir()
        out = symlink.ensure_junction(link, target)
        assert out.error and "non-empty" in out.error
        assert (link / "old_mod").is_dir()  # untouched

    def test_force_replaces_non_empty_dir(self, tmp_path: Path, target: Path) -> None:
        link = tmp_path / "link"
        link.mkdir()
        (link / "old_mod").mkdir()
        out = symlink.ensure_junction(link, target, force=True)
        assert out.created
        assert (link / "marker.txt").exists()

    def test_empty_dir_is_replaced_silently(self, tmp_path: Path, target: Path) -> None:
        link = tmp_path / "link"
        link.mkdir()
        assert symlink.ensure_junction(link, target).created

    def test_refuses_file_without_force(self, tmp_path: Path, target: Path) -> None:
        link = tmp_path / "link"
        link.write_text("", encoding="utf-8")
        assert symlink.ensure_junction(link, target).error
        assert symlink.ensure_junction(link, target, force=True).created

    def test_repoints_wrong_junction_only_with_force(self, tmp_path: Path, target: Path) -> None:
        other = tmp_path / "Other"
        other.mkdir()
        link = tmp_path / "link"
        assert symlink.ensure_junction(link, other).created
        out = symlink.ensure_junction(link, target)
        assert out.error and "already a junction" in out.error
        assert symlink.ensure_junction(link, target, force=True).created
        assert symlink.read_junction(link) == target.resolve()
        assert other.is_dir()  # repointing never touches the old target


class TestRmtree:
    def test_removes_read_only_files(self, tmp_path: Path) -> None:
        d = tmp_path / "mod"
        d.mkdir()
        f = d / "ro.txt"
        f.write_text("x", encoding="utf-8")
        f.chmod(0o444)
        symlink.rmtree(d)
        assert not d.exists()

    def test_rmtree_on_junction_does_not_delete_target(self, tmp_path: Path, target: Path) -> None:
        """A junction must be unlinked, never recursed into."""
        link = tmp_path / "link"
        symlink.ensure_junction(link, target)
        try:
            symlink.rmtree(link)
        except OSError:
            pass  # shutil refuses to rmtree a reparse point; that's acceptable
        assert (target / "marker.txt").exists()

    def test_long_path_does_not_resolve_junctions(self, tmp_path: Path, target: Path) -> None:
        link = tmp_path / "link"
        symlink.ensure_junction(link, target)
        assert symlink.long_path(link).endswith("\\link")
