from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import paths
from .config import REPO_ROOT, RIMWORLD_APP_ID, Settings
from .steam_client import RESULT_PREFIX


def _valid_result(action: str, result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if isinstance(result.get("error"), str):
        return True
    account = result.get("account")
    if not isinstance(account, str) or not account.isascii() or not account.isdecimal():
        return False
    if action == "probe":
        return result.get("ready") is True
    if action in {"subscribe", "unsubscribe"}:
        return (
            isinstance(result.get("succeeded"), list)
            and all(isinstance(p, str) and p.isdecimal() for p in result["succeeded"])
            and isinstance(result.get("failed"), list)
            and all(isinstance(row, dict) for row in result["failed"])
        )
    key = "results" if action == "search" else "items"
    rows = result.get(key)
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) and isinstance(row.get("pfid"), str) for row in rows
    ):
        return False
    if action == "state":
        return all(isinstance(row.get("subscribed"), bool) and "installed" in row for row in rows)
    return (
        all("file_type" in row and "consumer_app_id" in row for row in rows)
        and isinstance(result.get("failed"), list)
        and all(isinstance(row, dict) for row in result["failed"])
    )


def native_library(settings: Settings) -> Path | None:
    game = paths.discover(settings).game_dir
    if game is None:
        return None
    dll = Path(game.path) / "RimWorldWin64_Data/Plugins/x86_64/steam_api64.dll"
    return dll if dll.is_file() else None


async def request(settings: Settings, action: str, **arguments: Any) -> dict[str, Any]:
    dll = await asyncio.to_thread(native_library, settings)
    if dll is None:
        return {
            "error": "RimWorld's steam_api64.dll was not found.",
            "hint": "Install the Windows Steam edition of RimWorld and verify its files.",
        }
    mutation = action in {"subscribe", "unsubscribe"}
    suffix = " Subscription state is uncertain." if mutation else ""
    env = {**os.environ, "SteamAppId": str(RIMWORLD_APP_ID), "SteamGameId": str(RIMWORLD_APP_ID)}
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "src.rimworld_tools.steam_client",
            str(dll),
            "request",
            cwd=REPO_ROOT,
            env=env,
            stdin=asyncio.subprocess.PIPE,
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
        output, _ = await asyncio.wait_for(
            process.communicate(json.dumps({"action": action, **arguments}).encode("utf-8")),
            timeout=180,
        )
    except (TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        if isinstance(exc, asyncio.CancelledError):
            raise
        return {"error": "Steam helper timed out." + suffix, "hint": "Check Steam before retrying."}
    if process.returncode == 0:
        for line in reversed(output.decode("utf-8", "replace").splitlines()):
            if line.startswith(RESULT_PREFIX):
                try:
                    result = json.loads(line[len(RESULT_PREFIX) :])
                    if _valid_result(action, result):
                        return result
                except ValueError:
                    break
    return {
        "error": "Steam helper exited without a valid result." + suffix,
        "hint": "Check Steam and verify RimWorld's installed files before retrying.",
    }
