from __future__ import annotations

import ctypes as ct

import pytest

from src.rimworld_tools.steam_client import SteamClient, SubscriptionResult
from src.rimworld_tools.steam_transport import _valid_result
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


def test_query_released_on_callback_failure():
    client = object.__new__(SteamClient)
    client.ugc = 1
    client.long_description = client.return_children = client.cached_response = lambda *_: True
    client.send_query = lambda *_: 5
    released = []
    client.release_query = lambda _, handle: released.append(handle)

    def fail(*_):
        raise OSError("Disconnected")

    client.wait_result = fail
    with pytest.raises(OSError, match="Disconnected"):
        client.read_query(42)
    assert released == [42]


def test_details_keep_successful_chunks():
    client = object.__new__(SteamClient)
    client.ugc = 1
    calls = []
    client.create_details = lambda _, ids, count: calls.append(list(ids)) or len(calls)

    def query(handle, *_):
        if handle == 2:
            raise OSError("Disconnected")
        return {"items": [{"pfid": str(p)} for p in calls[-1]], "failed": []}

    client.read_query = query
    result = client.details([str(i) for i in range(1, 52)])
    assert len(result["items"]) == 50
    assert result["failed"] == [{"pfid": "51", "reason": "Disconnected"}]


def test_search_keeps_successful_page_and_native_sort_mapping():
    client = object.__new__(SteamClient)
    client.ugc = 1
    seen = []

    def bind(name, *_):
        if name == "CreateQueryAllUGCRequestPage":

            def create(*args):
                seen.append(args)
                return args[-1]

            return create
        return lambda *_: True

    client._ugc = bind

    def query(handle):
        if handle == 2:
            raise OSError("Disconnected")
        return {"items": [{"pfid": str(i)} for i in range(1, 51)], "total": 90, "failed": []}

    client.read_query = query
    result = client.search("", 70, ["Mod"], [], "updated", 90)
    assert seen[0][1] == 19
    assert len(result["results"]) == 50
    assert result["failed"] == [{"page": 2, "reason": "Disconnected"}]


def test_helper_protocol_rejects_incomplete_results():
    assert not _valid_result("details", {"account": "1"})
    assert not _valid_result("probe", {"account": "1"})
    assert not _valid_result("subscribe", {"account": "1", "succeeded": "1", "failed": []})
    assert _valid_result("probe", {"account": "1", "ready": True})


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
