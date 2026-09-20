from __future__ import annotations

import psutil

RIMWORLD_PROCESSES = frozenset({"rimworldwin64.exe", "rimworldwin.exe"})


def running(
    names: frozenset[str],
) -> list[str]:
    """Return matching Windows process names."""
    running: list[str] = []
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in names:
            running.append(name)
    return sorted(set(running))
