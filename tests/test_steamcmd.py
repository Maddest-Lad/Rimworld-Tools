from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.rimworld_tools import steamcmd
from src.rimworld_tools.config import Settings

SUCCESS_LOG = """\
Redirecting stderr to 'C:\\x\\steamcmd\\logs\\stderr.txt'
[  0%] Checking for available updates...
[----] Verifying installation...
Steam Console Client (c) Valve Corporation - version 1749081854
-- type 'quit' to exit --
Loading Steam API...OK
"@ShutdownOnFailedCommand" = "1"
Connecting anonymously to Steam Public...OK
Waiting for client config...OK
Waiting for user info...OK
Downloading item 2009463077 ...
Success. Downloaded item 2009463077 to "C:\\x\\steam\\steamapps\\workshop\\content\\294100\\2009463077" (1234567 bytes)
Downloading item 1631756268 ...
Success. Downloaded item 1631756268 to "C:\\x\\steam\\steamapps\\workshop\\content\\294100\\1631756268" (99 bytes)
"""

PARTIAL_FAILURE_LOG = """\
Connecting anonymously to Steam Public...OK
Downloading item 2009463077 ...
Success. Downloaded item 2009463077 to "C:\\x\\2009463077" (1234567 bytes)
Downloading item 9999999999 ...
ERROR! Download item 9999999999 failed (Failure).
Downloading item 8888888888 ...
ERROR! Timeout downloading item 8888888888
"""

NOT_LOGGED_ON_LOG = """\
Connecting anonymously to Steam Public...FAILED
ERROR! Not logged on.
"""

VPROF_LOG = """\
src/tier0/vprof.cpp: No room for new profile in vprof thread profile list, grow MAX_THREADS_TO_VPROF_AT_ONCE
"""


class TestLogParser:
    def test_all_success(self) -> None:
        p = steamcmd.LogParser(pending={"2009463077", "1631756268"})
        p.feed(SUCCESS_LOG)
        p.finish("exited")
        assert p.succeeded == ["2009463077", "1631756268"]
        assert p.failed == {}
        assert p.run_errors == []

    def test_partial_failure_with_reasons(self) -> None:
        p = steamcmd.LogParser(pending={"2009463077", "9999999999", "8888888888"})
        p.feed(PARTIAL_FAILURE_LOG)
        p.finish("exited")
        assert p.succeeded == ["2009463077"]
        assert p.failed["9999999999"] == "failed (Failure)."
        assert p.failed["8888888888"] == "download failed"

    def test_pending_at_exit_is_failure_regardless_of_exit_code(self) -> None:
        """Exit code 0 with no Success line must still count as failed."""
        p = steamcmd.LogParser(pending={"1", "2"})
        p.feed("Downloading item 1 ...\nSuccess. Downloaded item 1 to x\n")
        p.finish("no Success line")
        assert p.succeeded == ["1"]
        assert p.failed == {"2": "no Success line"}

    def test_not_logged_on_is_run_level(self) -> None:
        p = steamcmd.LogParser(pending={"1"})
        p.feed(NOT_LOGGED_ON_LOG)
        assert any("Not logged on" in e for e in p.run_errors)

    def test_vprof_overflow_detected(self) -> None:
        p = steamcmd.LogParser(pending=set())
        p.feed(VPROF_LOG)
        assert any("vprof" in e for e in p.run_errors)

    def test_partial_lines_across_feeds(self) -> None:
        p = steamcmd.LogParser(pending={"12345"})
        p.feed("Success. Downloaded ")
        assert p.succeeded == []
        p.feed("item 12345 to x\n")
        assert p.succeeded == ["12345"]

    def test_cr_and_ansi_normalised(self) -> None:
        p = steamcmd.LogParser(pending={"7"})
        p.feed(
            "\x1b[32m[ 50%] Downloading update\r[100%] done\rSuccess. Downloaded item 7 to x\r\n"
        )
        assert p.succeeded == ["7"]

    def test_flush_handles_trailing_line_without_newline(self) -> None:
        p = steamcmd.LogParser(pending={"7"})
        p.feed("Success. Downloaded item 7 to x")
        assert p.succeeded == []
        p.flush()
        assert p.succeeded == ["7"]


class TestScript:
    def test_script_shape(self, tmp_path: Path) -> None:
        script = steamcmd.write_script(tmp_path / "steam", ["1", "2"], validate=True)
        try:
            text = script.read_text(encoding="utf-8").splitlines()
        finally:
            script.unlink()
        assert text[0] == f'force_install_dir "{tmp_path / "steam"}"'
        assert text[1] == "login anonymous"
        assert text[2] == "workshop_download_item 294100 1 validate"
        assert text[3] == "workshop_download_item 294100 2 validate"
        assert text[-1] == "quit"

    def test_unique_per_call(self, tmp_path: Path) -> None:
        a = steamcmd.write_script(tmp_path, ["1"], False)
        b = steamcmd.write_script(tmp_path, ["1"], False)
        try:
            assert a != b
        finally:
            a.unlink()
            b.unlink()


def _settings(tmp_path: Path, max_items: int = 50) -> Settings:
    return Settings(
        steamcmd_prefix=tmp_path,
        mods_dir=tmp_path / "Mods",
        db_dir=tmp_path / "dbs",
        max_download_items=max_items,
        steam_web_api_key=None,
    )


class TestDownloadGuards:
    async def test_rejects_non_numeric_only(self, tmp_path: Path) -> None:
        out = await steamcmd.download(_settings(tmp_path), ["abc"])
        assert "error" in out

    async def test_rejects_oversized_with_hint(self, tmp_path: Path) -> None:
        out = await steamcmd.download(_settings(tmp_path, max_items=2), ["1", "2", "3"])
        assert "Too many" in out["error"]
        assert "RIMWORLD_TOOLS_MAX_DOWNLOAD_ITEMS" in out["hint"]

    async def test_requires_install(self, tmp_path: Path) -> None:
        out = await steamcmd.download(_settings(tmp_path), ["1"])
        assert "not installed" in out["error"]

    async def test_dedupes_and_separates_bad_ids(self, tmp_path: Path) -> None:
        good, bad = steamcmd._normalise_pfids(["1", 1, " 2 ", "x", "1"])
        assert good == ["1", "2"]
        assert bad == ["x"]


class TestBatchingWithFakeProcess:
    """Exercise the batch loop and log tailing against a fake steamcmd.exe."""

    @pytest.fixture
    def fake_steamcmd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Settings, list[list[str]]]:
        s = _settings(tmp_path)
        s.steamcmd_dir.mkdir(parents=True)
        (s.steamcmd_dir / "logs").mkdir()
        s.steamcmd_exe.write_text("", encoding="utf-8")
        calls: list[list[str]] = []

        async def fake_run_batch(settings: Settings, pfids: list[str], validate: bool, t: float):
            calls.append(list(pfids))
            failed = {p: "failed (Failure)." for p in pfids if p.endswith("9")}
            return steamcmd.BatchResult(
                succeeded=[p for p in pfids if p not in failed],
                failed=failed,
                run_errors=[],
                timed_out=False,
                duration_s=0.1,
                excerpt=[],
            )

        monkeypatch.setattr(steamcmd, "run_batch", fake_run_batch)
        return s, calls

    async def test_splits_into_batches_of_25(
        self, fake_steamcmd: tuple[Settings, list[list[str]]]
    ) -> None:
        settings, calls = fake_steamcmd
        pfids = [str(i) for i in range(1, 31)]
        out = await steamcmd.download(settings, pfids)
        assert out["batches_run"] == 2
        assert [len(c) for c in calls] == [25, 5]
        assert set(out["succeeded"]) == {p for p in pfids if not p.endswith("9")}
        assert {f["pfid"] for f in out["failed"]} == {"9", "19", "29"}
        assert "hint" in out

    async def test_login_failure_short_circuits(
        self, fake_steamcmd: tuple[Settings, list[list[str]]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings, _ = fake_steamcmd

        async def failing(settings: Settings, pfids: list[str], validate: bool, t: float):
            return steamcmd.BatchResult(
                succeeded=[],
                failed={p: "no Success line" for p in pfids},
                run_errors=["Not logged on — login failure"],
                timed_out=False,
                duration_s=0.1,
                excerpt=[],
            )

        monkeypatch.setattr(steamcmd, "run_batch", failing)
        pfids = [str(i) for i in range(1, 31)]
        out = await steamcmd.download(settings, pfids)
        assert out["batches_run"] == 1
        reasons = {f["reason"] for f in out["failed"]}
        assert any("not attempted" in r for r in reasons)
        assert "log on" in out["hint"]


class TestTailer:
    async def test_reads_incrementally_and_handles_truncation(self, tmp_path: Path) -> None:
        log = tmp_path / "console_log.txt"
        log.write_text("old line\n", encoding="utf-8")
        parser = steamcmd.LogParser(pending={"1", "2"})
        stop = asyncio.Event()
        task = asyncio.create_task(steamcmd._tail(log, log.stat().st_size, parser, stop))
        await asyncio.sleep(0.05)
        with log.open("a", encoding="utf-8") as fh:
            fh.write("Success. Downloaded item 1 to x\n")
        await asyncio.sleep(0.4)
        assert parser.succeeded == ["1"]
        # Simulate rotation: file shrinks, new content from offset 0.
        log.write_text("Success. Downloaded item 2 to y\n", encoding="utf-8")
        await asyncio.sleep(0.4)
        stop.set()
        await task
        assert parser.succeeded == ["1", "2"]
        assert "old line" not in parser.excerpt
