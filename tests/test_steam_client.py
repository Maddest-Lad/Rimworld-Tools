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
