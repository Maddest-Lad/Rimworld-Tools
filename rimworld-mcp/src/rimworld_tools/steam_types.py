from __future__ import annotations

import ctypes as ct


# Steamworks Windows ABI: fixed buffers and 8-byte callback packing.
class UGCDetails(ct.Structure):
    _pack_ = 8
    _fields_ = [
        ("pfid", ct.c_uint64),
        ("result", ct.c_int32),
        ("file_type", ct.c_int32),
        ("creator_app", ct.c_uint32),
        ("consumer_app", ct.c_uint32),
        ("title", ct.c_char * 129),
        ("description", ct.c_char * 8000),
        ("owner", ct.c_uint64),
        ("created", ct.c_uint32),
        ("updated", ct.c_uint32),
        ("added", ct.c_uint32),
        ("visibility", ct.c_int32),
        ("banned", ct.c_bool),
        ("accepted", ct.c_bool),
        ("tags_truncated", ct.c_bool),
        ("tags", ct.c_char * 1025),
        ("file", ct.c_uint64),
        ("preview", ct.c_uint64),
        ("filename", ct.c_char * 260),
        ("file_size", ct.c_int32),
        ("preview_size", ct.c_int32),
        ("url", ct.c_char * 256),
        ("votes_up", ct.c_uint32),
        ("votes_down", ct.c_uint32),
        ("score", ct.c_float),
        ("num_children", ct.c_uint32),
    ]


class QueryCompleted(ct.Structure):
    _pack_ = 8
    _fields_ = [
        ("handle", ct.c_uint64),
        ("result", ct.c_int32),
        ("count", ct.c_uint32),
        ("total", ct.c_uint32),
        ("cached", ct.c_bool),
        ("cursor", ct.c_char * 256),
    ]
