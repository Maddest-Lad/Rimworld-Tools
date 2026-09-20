from __future__ import annotations

import ctypes as ct

import pytest

from src.rimworld_tools.steam_client import SteamClient, SubscriptionResult
from src.rimworld_tools.steam_types import QueryCompleted, UGCDetails
from src.rimworld_tools.workshop_ids import normalise, parse_url


def test_windows_abi_layout():
    assert ct.sizeof(SubscriptionResult) == 16
    assert ct.sizeof(QueryCompleted) == 280
    assert UGCDetails.owner.offset == 8160
    assert ct.sizeof(UGCDetails) == 9776


def test_query_released_on_option_failure():
    client = object.__new__(SteamClient)
    client.ugc = 1
    client.long_description = client.return_children = client.cached_response = lambda *_: False
    released = []
    client.release_query = lambda _, handle: released.append(handle)
    with pytest.raises(OSError):
        client.read_query(42)
    assert released == [42]


def test_ids_and_urls():
    assert normalise([True, -1, 0, 2**64, "bad", "001", 1]) == (
        ["1"],
        ["True", "-1", "0", str(2**64), "bad"],
    )
    assert parse_url("steamcommunity.com/sharedfiles/filedetails/?id=001") == "1"
    assert parse_url("https://unrelated.example/?id=1") is None


def test_subscription_changes_validate_app_and_allow_unavailable_unsubscribe():
    client = object.__new__(SteamClient)
    client.subscribed_ids = lambda: ["1", "2"]
    client.details = lambda _: {
        "items": [
            {"pfid": "3", "consumer_app_id": 123, "file_type": 0},
            {"pfid": "4", "consumer_app_id": 294100, "file_type": 2},
            {"pfid": "5", "consumer_app_id": 294100, "file_type": 0},
        ],
        "failed": [],
    }
    dispatched = []

    def change(ids, subscribe):
        dispatched.append((ids, subscribe))
        return {"succeeded": ids, "failed": []}

    client._change_confirmed = change
    result = client.change(["1", "3", "4", "5"], True)
    assert result["already_satisfied"] == ["1"]
    assert dispatched == [(["5"], True)]
    assert len(result["failed"]) == 2
    client.details = lambda _: pytest.fail("Unsubscribe must not require public item metadata")
    result = client.change(["2", "6"], False)
    assert result["already_satisfied"] == ["6"]
    assert dispatched[-1] == (["2"], False)
