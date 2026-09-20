from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import acf, paths, webapi
from .config import REPO_ROOT, RIMWORLD_APP_ID, Settings
from .steam_client import RESULT_PREFIX

MAX_ITEMS = 50


def native_library(settings: Settings) -> Path | None:
    game = paths.discover(settings).game_dir
    if game is None:
        return None
    dll = Path(game.path) / "RimWorldWin64_Data/Plugins/x86_64/steam_api64.dll"
    return dll if dll.is_file() else None


def status(settings: Settings) -> dict[str, Any]:
    dll = native_library(settings)
    running = bool(acf.steam_processes_running({"steam.exe"}))
    return {
        "steam_running": running,
        "steam_api_dll": str(dll) if dll else None,
        "hint": "Subscriptions use the signed-in Steam account; Steam manages downloads and removal.",
    }


async def run_client(dll: Path, action: str, pfids: list[str]) -> dict[str, Any]:
    env = {**os.environ, "SteamAppId": str(RIMWORLD_APP_ID), "SteamGameId": str(RIMWORLD_APP_ID)}
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "src.rimworld_tools.steam_client",
            str(dll),
            action,
            *pfids,
            cwd=REPO_ROOT,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except OSError as exc:
        return {
            "error": f"Could not start Steam helper: {exc}",
            "hint": "Check the Python installation.",
        }
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=45)
    except (TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            process.kill()
        await process.wait()
        if isinstance(exc, asyncio.CancelledError):
            raise
        return {
            "error": "Steam helper timed out; subscription state is uncertain.",
            "hint": "Check Steam before retrying.",
        }
    if process.returncode == 0:
        for line in reversed(output.decode("utf-8", errors="replace").splitlines()):
            if line.startswith(RESULT_PREFIX):
                try:
                    result = json.loads(line[len(RESULT_PREFIX) :])
                    if isinstance(result, dict):
                        return result
                except ValueError:
                    break
    return {
        "error": "Steam helper exited without a result; subscription state is uncertain.",
        "hint": "Check Steam and verify RimWorld's installed files before retrying.",
    }


async def change(settings: Settings, pfids: list[str | int], subscribe: bool) -> dict[str, Any]:
    good = []
    failed = []
    for value in pfids:
        pfid = str(value).strip()
        if (
            not pfid.isascii()
            or not pfid.isdecimal()
            or len(pfid) > 20
            or not 0 < int(pfid) < 2**64
        ):
            failed.append({"pfid": str(value), "reason": "Expected a positive 64-bit Workshop id."})
        elif str(int(pfid)) not in good:
            good.append(str(int(pfid)))
    if len(good) > MAX_ITEMS:
        return {
            "error": f"At most {MAX_ITEMS} items per subscription call.",
            "hint": "Split the list into batches.",
        }
    if not good:
        return {"succeeded": [], "failed": failed}
    dll = await asyncio.to_thread(native_library, settings)
    if dll is None:
        return {
            "error": "RimWorld's steam_api64.dll was not found.",
            "hint": "Install the Windows Steam edition of RimWorld and verify its files.",
        }
    if subscribe:
        # Validate against live Workshop metadata before changing the user's subscriptions.
        details = await asyncio.to_thread(webapi.file_details, good, settings.steam_web_api_key)
        eligible = []
        for pfid in good:
            item = details.items.get(pfid)
            if item is None or item["unpublished"]:
                failed.append(
                    {"pfid": pfid, "reason": "Workshop item unavailable or lookup failed."}
                )
            elif str(item.get("consumer_app_id")) != str(RIMWORLD_APP_ID):
                failed.append({"pfid": pfid, "reason": "Not a RimWorld Workshop item."})
            else:
                eligible.append(pfid)
        good = eligible
    if not good:
        return {"succeeded": [], "failed": failed}
    result = await run_client(dll, "subscribe" if subscribe else "unsubscribe", good)
    if "error" in result:
        return {
            **result,
            "succeeded": [],
            "failed": failed + [{"pfid": p, "reason": result["error"]} for p in good],
        }
    result["failed"] = failed + result["failed"]
    result["hint"] = (
        "Subscriptions confirmed; Steam will download the mods asynchronously."
        if subscribe
        else "Unsubscriptions confirmed; Steam manages removal after the game exits. Local Mods copies are untouched."
    )
    return result
