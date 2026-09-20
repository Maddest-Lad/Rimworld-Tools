from __future__ import annotations

import ctypes as ct
import json
import sys
import time
from pathlib import Path

from .config import RIMWORLD_APP_ID

RESULT_PREFIX = "RIMWORLD_TOOLS_RESULT:"
CALL_TIMEOUT = 30


class SubscriptionResult(ct.Structure):
    # Steamworks callbacks use 8-byte packing on Windows, including the padding after EResult.
    _pack_ = 8
    _fields_ = [("result", ct.c_int32), ("pfid", ct.c_uint64)]


class SteamClient:
    """Small binding to the Steamworks DLL shipped with the installed Windows game."""

    def __init__(self, dll_path: Path) -> None:
        if sys.platform != "win32" or ct.sizeof(ct.c_void_p) != 8:
            raise OSError("Steam subscriptions require 64-bit Python on Windows.")
        self.dll = ct.CDLL(str(dll_path))
        self.init = self._bind("SteamAPI_Init", ct.c_bool)
        self.shutdown = self._bind("SteamAPI_Shutdown", None)
        self.run_callbacks = self._bind("SteamAPI_RunCallbacks", None)
        self.get_ugc = self._bind("SteamAPI_SteamUGC_v016", ct.c_void_p)
        self.get_utils = self._bind("SteamAPI_SteamUtils_v010", ct.c_void_p)
        self.get_app_id = self._bind("SteamAPI_ISteamUtils_GetAppID", ct.c_uint32, ct.c_void_p)
        self.subscribe = self._bind(
            "SteamAPI_ISteamUGC_SubscribeItem", ct.c_uint64, ct.c_void_p, ct.c_uint64
        )
        self.unsubscribe = self._bind(
            "SteamAPI_ISteamUGC_UnsubscribeItem", ct.c_uint64, ct.c_void_p, ct.c_uint64
        )
        self.item_state = self._bind(
            "SteamAPI_ISteamUGC_GetItemState", ct.c_uint32, ct.c_void_p, ct.c_uint64
        )
        self.completed = self._bind(
            "SteamAPI_ISteamUtils_IsAPICallCompleted",
            ct.c_bool,
            ct.c_void_p,
            ct.c_uint64,
            ct.POINTER(ct.c_bool),
        )
        self.result = self._bind(
            "SteamAPI_ISteamUtils_GetAPICallResult",
            ct.c_bool,
            ct.c_void_p,
            ct.c_uint64,
            ct.c_void_p,
            ct.c_int,
            ct.c_int,
            ct.POINTER(ct.c_bool),
        )

    def _bind(self, name, restype, *argtypes):
        function = getattr(self.dll, name)
        function.restype = restype
        function.argtypes = list(argtypes)
        return function

    def __enter__(self):
        if not self.init():
            raise OSError(
                "Steam API initialization failed. Start Steam and sign in to an account that owns RimWorld."
            )
        try:
            self.ugc = self.get_ugc()
            self.utils = self.get_utils()
            if not self.ugc or not self.utils or self.get_app_id(self.utils) != RIMWORLD_APP_ID:
                raise OSError("Steam did not provide the RimWorld Workshop interfaces.")
        except BaseException:
            self.shutdown()
            raise
        return self

    def __exit__(self, *_):
        self.shutdown()

    def change(self, pfids: list[str], subscribe: bool) -> dict:
        succeeded = []
        failed = []
        pending = {}
        callback = 1313 if subscribe else 1315
        operation = self.subscribe if subscribe else self.unsubscribe
        for pfid in pfids:
            if not subscribe and not self.item_state(self.ugc, int(pfid)) & 1:
                failed.append(
                    {
                        "pfid": pfid,
                        "reason": "Steam does not report this item as subscribed for RimWorld.",
                    }
                )
                continue
            handle = operation(self.ugc, int(pfid))
            if handle:
                pending[handle] = pfid
            else:
                failed.append(
                    {"pfid": pfid, "reason": "Steam rejected the request before queuing it."}
                )
        deadline = time.monotonic() + CALL_TIMEOUT
        while pending and time.monotonic() < deadline:
            self.run_callbacks()
            for handle, pfid in list(pending.items()):
                io_failed = ct.c_bool()
                if not self.completed(self.utils, handle, ct.byref(io_failed)):
                    continue
                result = SubscriptionResult()
                ok = not io_failed.value and self.result(
                    self.utils,
                    handle,
                    ct.byref(result),
                    ct.sizeof(result),
                    callback,
                    ct.byref(io_failed),
                )
                if ok and not io_failed.value and result.result == 1 and result.pfid == int(pfid):
                    succeeded.append(pfid)
                else:
                    failed.append(
                        {
                            "pfid": pfid,
                            "reason": (
                                f"Steam returned EResult {result.result} for item {result.pfid}; request was not confirmed."
                                if ok and not io_failed.value
                                else "Steam connection failed; subscription state is uncertain."
                            ),
                        }
                    )
                del pending[handle]
            if pending:
                time.sleep(0.05)
        failed.extend(
            {"pfid": p, "reason": "Steam timed out; subscription state is uncertain."}
            for p in pending.values()
        )
        return {"succeeded": succeeded, "failed": failed}


def main() -> None:
    """Run native code in a short-lived process so its output cannot corrupt MCP stdio."""
    dll, action, *pfids = sys.argv[1:]
    if action not in {"subscribe", "unsubscribe", "probe"}:
        raise ValueError("Unknown Steam action")
    try:
        with SteamClient(Path(dll)) as client:
            result = (
                {"ready": True}
                if action == "probe"
                else client.change(pfids, action == "subscribe")
            )
    except (OSError, AttributeError) as exc:
        result = {
            "error": str(exc),
            "hint": "Use the installed Steam edition of RimWorld and keep Steam signed in.",
        }
    print(RESULT_PREFIX + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
