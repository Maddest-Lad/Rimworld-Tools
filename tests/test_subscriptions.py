from __future__ import annotations

import asyncio
import ctypes as ct
from unittest.mock import AsyncMock

import pytest

from src.rimworld_tools import steam_client, subscriptions, webapi
from src.rimworld_tools.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path, None, tmp_path / "dbs", 50, None)


async def test_subscribe_validates_ids_and_game_before_mutating(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(subscriptions, "native_library", lambda _: tmp_path / "steam_api64.dll")
    monkeypatch.setattr(
        webapi,
        "file_details",
        lambda *_: webapi.ChunkedResult(
            items={
                "1": {"unpublished": False, "consumer_app_id": 294100},
                "2": {"unpublished": False, "consumer_app_id": 123},
                "3": {"unpublished": True},
            }
        ),
    )
    helper = AsyncMock(return_value={"succeeded": ["1"], "failed": []})
    monkeypatch.setattr(subscriptions, "run_client", helper)
    result = await subscriptions.change(settings, ["001", 1, 2, 3, "bad", 0, 2**64], True)
    assert result["succeeded"] == ["1"]
    assert len(result["failed"]) == 5
    assert helper.call_args.args[1:] == ("subscribe", ["1"])


async def test_batch_limit_does_not_start_helper(settings, monkeypatch):
    helper = AsyncMock()
    monkeypatch.setattr(subscriptions, "run_client", helper)
    assert "error" in await subscriptions.change(settings, list(range(1, 52)), True)
    helper.assert_not_called()


async def test_helper_failure_keeps_per_item_results(settings, monkeypatch, tmp_path):
    monkeypatch.setattr(subscriptions, "native_library", lambda _: tmp_path / "steam_api64.dll")
    helper = AsyncMock(return_value={"error": "Steam offline", "hint": "Sign in"})
    monkeypatch.setattr(subscriptions, "run_client", helper)
    result = await subscriptions.change(settings, [1, "bad"], False)
    assert result["succeeded"] == []
    assert {row["pfid"] for row in result["failed"]} == {"1", "bad"}


@pytest.mark.parametrize("subscribe,callback", [(True, 1313), (False, 1315)])
def test_native_call_results_are_confirmed_per_item(monkeypatch, subscribe, callback):
    client = object.__new__(steam_client.SteamClient)
    client.ugc = client.utils = 1
    client.subscribe = client.unsubscribe = lambda _, pfid: pfid if pfid != 4 else 0
    client.item_state = lambda *_: 1
    client.run_callbacks = lambda: None
    client.completed = lambda *_: True

    def result(_, handle, pointer, size, expected_callback, io_failed):
        assert expected_callback == callback
        assert size == 16
        record = ct.cast(pointer, ct.POINTER(steam_client.SubscriptionResult)).contents
        record.result = 1 if handle != 2 else 15
        record.pfid = handle if handle != 3 else 999
        return True

    client.result = result
    result = client.change(["1", "2", "3", "4"], subscribe)
    assert result["succeeded"] == ["1"]
    assert {row["pfid"] for row in result["failed"]} == {"2", "3", "4"}


def test_native_timeout_is_not_success(monkeypatch):
    client = object.__new__(steam_client.SteamClient)
    client.ugc = client.utils = 1
    client.subscribe = lambda *_: 10
    client.run_callbacks = lambda: None
    client.completed = lambda *_: False
    monkeypatch.setattr(steam_client, "CALL_TIMEOUT", 0)
    result = client.change(["1"], True)
    assert result["succeeded"] == []
    assert "uncertain" in result["failed"][0]["reason"]


@pytest.mark.parametrize("exception", [TimeoutError, asyncio.CancelledError])
async def test_helper_is_reaped_on_timeout_or_cancellation(tmp_path, monkeypatch, exception):
    class Process:
        returncode = None
        killed = False
        waited = False

        async def communicate(self):
            raise exception()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.waited = True

    process = Process()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    if exception is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await subscriptions.run_client(tmp_path / "steam_api64.dll", "subscribe", ["1"])
    else:
        result = await subscriptions.run_client(tmp_path / "steam_api64.dll", "subscribe", ["1"])
        assert "uncertain" in result["error"]
    assert process.killed and process.waited


async def test_helper_output_does_not_leak_native_logs(tmp_path, monkeypatch):
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (
        b'native log\nRIMWORLD_TOOLS_RESULT:{"succeeded": ["1"], "failed": []}\n',
        None,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    assert await subscriptions.run_client(tmp_path / "steam_api64.dll", "subscribe", ["1"]) == {
        "succeeded": ["1"],
        "failed": [],
    }
