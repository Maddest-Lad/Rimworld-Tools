from __future__ import annotations

import ctypes as ct
import json
import sys
import time
from pathlib import Path

from .config import RIMWORLD_APP_ID
from .steam_types import QueryCompleted, UGCDetails

RESULT_PREFIX = "RIMWORLD_TOOLS_RESULT:"
CALL_TIMEOUT = 30
SORT_MODES = {"relevance": 11, "trend": 3, "recent": 1, "top": 0, "updated": 19}


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
        self.get_user = self._bind("SteamAPI_SteamUser_v021", ct.c_void_p)
        self.logged_on = self._bind("SteamAPI_ISteamUser_BLoggedOn", ct.c_bool, ct.c_void_p)
        self.user_id = self._bind("SteamAPI_ISteamUser_GetSteamID", ct.c_uint64, ct.c_void_p)
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
        self.create_details = self._ugc(
            "CreateQueryUGCDetailsRequest", ct.c_uint64, ct.POINTER(ct.c_uint64), ct.c_uint32
        )
        self.send_query = self._ugc("SendQueryUGCRequest", ct.c_uint64, ct.c_uint64)
        self.query_result = self._ugc(
            "GetQueryUGCResult", ct.c_bool, ct.c_uint64, ct.c_uint32, ct.POINTER(UGCDetails)
        )
        self.release_query = self._ugc("ReleaseQueryUGCRequest", ct.c_bool, ct.c_uint64)
        self.long_description = self._ugc(
            "SetReturnLongDescription", ct.c_bool, ct.c_uint64, ct.c_bool
        )
        self.return_children = self._ugc("SetReturnChildren", ct.c_bool, ct.c_uint64, ct.c_bool)
        self.query_children = self._ugc(
            "GetQueryUGCChildren",
            ct.c_bool,
            ct.c_uint64,
            ct.c_uint32,
            ct.POINTER(ct.c_uint64),
            ct.c_uint32,
        )
        self.cached_response = self._ugc(
            "SetAllowCachedResponse", ct.c_bool, ct.c_uint64, ct.c_uint32
        )

    def _ugc(self, name, restype, *args):
        return self._bind("SteamAPI_ISteamUGC_" + name, restype, ct.c_void_p, *args)

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
            self.user = self.get_user()
            if not self.ugc or not self.utils or self.get_app_id(self.utils) != RIMWORLD_APP_ID:
                raise OSError("Steam did not provide the RimWorld Workshop interfaces.")
            if not self.user or not self.logged_on(self.user):
                raise OSError(
                    "Steam is offline or signed out. Sign in and connect Steam to the internet."
                )
            self.account = str(self.user_id(self.user))
        except BaseException:
            self.shutdown()
            raise
        return self

    def __exit__(self, *_):
        self.shutdown()

    def wait_result(self, handle, record_type, callback):
        if not handle:
            raise OSError("Steam rejected the API request.")
        deadline = time.monotonic() + CALL_TIMEOUT
        while time.monotonic() < deadline:
            self.run_callbacks()
            failed = ct.c_bool()
            if self.completed(self.utils, handle, ct.byref(failed)):
                record = record_type()
                if (
                    failed.value
                    or not self.result(
                        self.utils,
                        handle,
                        ct.byref(record),
                        ct.sizeof(record),
                        callback,
                        ct.byref(failed),
                    )
                    or failed.value
                ):
                    raise OSError("Steam API call failed or returned an incompatible callback.")
                return record
            time.sleep(0.05)
        raise OSError("Steam API call timed out.")

    def read_query(self, handle: int, description: bool = False, children: bool = False) -> dict:
        if handle in (0, 2**64 - 1):
            raise OSError("Steam rejected the Workshop query.")
        try:
            for function, value in [
                (self.long_description, description),
                (self.return_children, children),
                (self.cached_response, 0),
            ]:
                if not function(self.ugc, handle, value):
                    raise OSError("Steam rejected a Workshop query option.")
            done = self.wait_result(self.send_query(self.ugc, handle), QueryCompleted, 3401)
            if done.result != 1 or done.handle != handle:
                raise OSError(f"Workshop query failed (EResult {done.result}).")
            items, failed = [], []
            for index in range(done.count):
                row = UGCDetails()
                if not self.query_result(self.ugc, handle, index, ct.byref(row)):
                    failed.append(
                        {"index": index, "reason": "Steam could not read the query result."}
                    )
                    continue
                pfid = str(row.pfid)
                if row.result != 1:
                    failed.append(
                        {
                            "pfid": pfid,
                            "result": row.result,
                            "reason": "Item unavailable to this account.",
                        }
                    )
                    continue
                item = {
                    "pfid": pfid,
                    "title": row.title.decode("utf-8", "replace"),
                    "file_type": row.file_type,
                    "consumer_app_id": row.consumer_app,
                    "creator": str(row.owner),
                    "time_created": row.created,
                    "time_updated": row.updated,
                    "file_size": row.file_size if row.file_size >= 0 else None,
                    "tags": row.tags.decode("utf-8", "replace").split(",") if row.tags else [],
                    "tags_truncated": bool(row.tags_truncated),
                    "visibility": row.visibility,
                    "url": f"https://steamcommunity.com/sharedfiles/filedetails/?id={pfid}",
                    "unpublished": False,
                }
                if description:
                    item["description"] = row.description.decode("utf-8", "replace")
                    item["description_may_be_truncated"] = len(row.description) >= 7996
                if children and row.file_type == 2:
                    if row.num_children > 10000:
                        failed.append(
                            {"pfid": pfid, "reason": "Collection exceeds the 10000-item limit."}
                        )
                        continue
                    ids = (ct.c_uint64 * row.num_children)()
                    if row.num_children and not self.query_children(
                        self.ugc, handle, index, ids, len(ids)
                    ):
                        failed.append(
                            {"pfid": pfid, "reason": "Steam could not read collection members."}
                        )
                        continue
                    item["children"] = [str(p) for p in ids]
                items.append(item)
            return {"items": items, "failed": failed, "total": done.total}
        finally:
            self.release_query(self.ugc, handle)

    def details(self, pfids: list[str], description: bool = False, children: bool = False) -> dict:
        items, failed = [], []
        for start in range(0, len(pfids), 50):
            chunk = pfids[start : start + 50]
            ids = (ct.c_uint64 * len(chunk))(*(int(p) for p in chunk))
            try:
                result = self.read_query(
                    self.create_details(self.ugc, ids, len(ids)), description, children
                )
                items.extend(result["items"])
                reasons = {r.get("pfid"): r for r in result["failed"]}
                returned = {r["pfid"] for r in result["items"]}
                failed.extend(
                    reasons.get(p, {"pfid": p, "reason": "No item returned by Steam."})
                    for p in chunk
                    if p not in returned
                )
            except OSError as exc:
                failed.extend({"pfid": p, "reason": str(exc)} for p in chunk)
        return {"items": items, "failed": failed}

    def search(
        self, query: str, limit: int, required: list[str], excluded: list[str], sort: str, days: int
    ) -> dict:
        create = self._ugc(
            "CreateQueryAllUGCRequestPage",
            ct.c_uint64,
            ct.c_int,
            ct.c_int,
            ct.c_uint32,
            ct.c_uint32,
            ct.c_uint32,
        )
        search_text = self._ugc("SetSearchText", ct.c_bool, ct.c_uint64, ct.c_char_p)
        required_tag = self._ugc("AddRequiredTag", ct.c_bool, ct.c_uint64, ct.c_char_p)
        excluded_tag = self._ugc("AddExcludedTag", ct.c_bool, ct.c_uint64, ct.c_char_p)
        trend_days = self._ugc("SetRankedByTrendDays", ct.c_bool, ct.c_uint64, ct.c_uint32)
        items, failed = [], []
        total = None
        for page in range(1, (limit + 49) // 50 + 1):
            handle = create(self.ugc, SORT_MODES[sort], 0, RIMWORLD_APP_ID, RIMWORLD_APP_ID, page)
            if handle in (0, 2**64 - 1):
                failed.append({"page": page, "reason": "Steam rejected the search query."})
                break
            try:
                options = [(required_tag, tag.encode("utf-8")) for tag in required]
                options += [(excluded_tag, tag.encode("utf-8")) for tag in excluded]
                if query:
                    options.append((search_text, query.encode("utf-8")))
                if sort == "trend":
                    options.append((trend_days, days))
                for function, value in options:
                    if not function(self.ugc, handle, value):
                        raise OSError("Steam rejected a search filter.")
            except OSError as exc:
                self.release_query(self.ugc, handle)
                failed.append({"page": page, "reason": str(exc)})
                break
            try:
                result = self.read_query(handle)
            except OSError as exc:
                failed.append({"page": page, "reason": str(exc)})
                break
            total = result["total"]
            items.extend(result["items"])
            failed.extend({**row, "page": page} for row in result["failed"])
            if page * 50 >= total:
                break
        return {"results": items[:limit], "total": total, "failed": failed}

    def subscribed_ids(self) -> list[str]:
        create = self._ugc(
            "CreateQueryUserUGCRequest",
            ct.c_uint64,
            ct.c_uint32,
            ct.c_int,
            ct.c_int,
            ct.c_int,
            ct.c_uint32,
            ct.c_uint32,
            ct.c_uint32,
        )
        ids = []
        for page in range(1, 201):
            handle = create(
                self.ugc,
                int(self.account) & 0xFFFFFFFF,
                6,
                -1,
                0,
                RIMWORLD_APP_ID,
                RIMWORLD_APP_ID,
                page,
            )
            result = self.read_query(handle)
            for row in result["items"] + result["failed"]:
                if not row.get("pfid") or row["pfid"] == "0":
                    raise OSError("Steam returned an incomplete subscription list; retry.")
                ids.append(row["pfid"])
            if page * 50 >= result["total"]:
                return list(dict.fromkeys(ids))
        raise OSError("Steam subscriptions exceed the supported 10000-item limit.")

    def installation_state(self, pfids: list[str] | None = None) -> dict:
        subscribed = set(self.subscribed_ids())
        selected = sorted(subscribed, key=int) if pfids is None else pfids
        install = self._ugc(
            "GetItemInstallInfo",
            ct.c_bool,
            ct.c_uint64,
            ct.POINTER(ct.c_uint64),
            ct.c_void_p,
            ct.c_uint32,
            ct.POINTER(ct.c_uint32),
        )
        download = self._ugc(
            "GetItemDownloadInfo",
            ct.c_bool,
            ct.c_uint64,
            ct.POINTER(ct.c_uint64),
            ct.POINTER(ct.c_uint64),
        )
        items = []
        for pfid in selected:
            if pfid not in subscribed:
                items.append({"pfid": pfid, "subscribed": False, "installed": False})
                continue
            flags = self.item_state(self.ugc, int(pfid))
            row = {
                "pfid": pfid,
                "subscribed": True,
                "installed": bool(flags & 4),
                "needs_update": bool(flags & 8),
                "downloading": bool(flags & 16),
                "download_pending": bool(flags & 32),
                "source": "steam",
            }
            if flags & 4:
                size, timestamp = ct.c_uint64(), ct.c_uint32()
                folder = ct.create_string_buffer(32768)
                if install(
                    self.ugc, int(pfid), ct.byref(size), folder, len(folder), ct.byref(timestamp)
                ):
                    row.update(
                        path=folder.value.decode("utf-8", "replace"),
                        installed_at=timestamp.value,
                        size_on_disk=size.value,
                    )
                else:
                    row["installed"] = None
                    row["notice"] = "Steam install information is not available yet."
            downloaded, total = ct.c_uint64(), ct.c_uint64()
            if download(self.ugc, int(pfid), ct.byref(downloaded), ct.byref(total)):
                row.update(bytes_downloaded=downloaded.value, bytes_total=total.value)
            items.append(row)
        return {"items": items}

    def change(self, pfids: list[str], subscribe: bool) -> dict:
        subscribed = set(self.subscribed_ids())
        satisfied = [p for p in pfids if (p in subscribed) == subscribe]
        pending = [p for p in pfids if p not in satisfied]
        failed = []
        if subscribe and pending:
            details = self.details(pending)
            failed.extend(details["failed"])
            pending = []
            for item in details["items"]:
                if item["consumer_app_id"] == RIMWORLD_APP_ID and item["file_type"] == 0:
                    pending.append(item["pfid"])
                else:
                    failed.append(
                        {"pfid": item["pfid"], "reason": "Not a subscribable RimWorld mod."}
                    )
        result = self._change_confirmed(pending, subscribe)
        result["already_satisfied"] = satisfied
        result["succeeded"] = satisfied + result["succeeded"]
        result["failed"] = failed + result["failed"]
        return result

    def _change_confirmed(self, pfids: list[str], subscribe: bool) -> dict:
        succeeded = []
        failed = []
        pending = {}
        callback = 1313 if subscribe else 1315
        operation = self.subscribe if subscribe else self.unsubscribe
        for pfid in pfids:
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
    dll, _ = sys.argv[1:]
    request = json.loads(sys.stdin.read())
    action = request["action"]
    if action not in {"subscribe", "unsubscribe", "probe", "details", "search", "state"}:
        raise ValueError("Unknown Steam action")
    try:
        with SteamClient(Path(dll)) as client:
            if request.get("account", client.account) != client.account:
                raise OSError("The Steam account changed during the operation; retry.")
            if action == "probe":
                result = {"ready": True}
            elif action == "details":
                result = client.details(
                    request["pfids"],
                    request.get("description", False),
                    request.get("children", False),
                )
            elif action == "search":
                result = client.search(
                    request["query"],
                    request["limit"],
                    request["required"],
                    request["excluded"],
                    request["sort"],
                    request["days"],
                )
            elif action == "state":
                result = client.installation_state(request.get("pfids"))
            else:
                result = client.change(request["pfids"], action == "subscribe")
            result["account"] = client.account
    except (OSError, AttributeError) as exc:
        result = {
            "error": str(exc),
            "hint": "Use the installed Steam edition of RimWorld and keep Steam signed in.",
        }
    print(RESULT_PREFIX + json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
