from __future__ import annotations

import psutil

# RimWorld.exe is the 1.7 (Waylith) executable. The Unity names stay because the main Steam branch
# is still 1.6: a missed running game would overwrite a ModsConfig.xml write on exit.
RIMWORLD_PROCESSES = frozenset({"rimworld.exe", "rimworldwin64.exe", "rimworldwin.exe"})


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
