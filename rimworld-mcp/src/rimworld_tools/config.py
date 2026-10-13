from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RIMWORLD_APP_ID = 294100

RIMWORLD_APP_IDS: dict[str, int] = {
    "base": 294100,
    "royalty": 1149640,
    "ideology": 1392840,
    "biotech": 1826140,
    "anomaly": 2380740,
    "odyssey": 3022790,
}

# 1.7 (Waylith engine) loads 1.6 mods unchanged; the game still marks them "not made for this
# version" until authors add 1.7. Searches and version advisories treat that pair as low risk.
RUNS_PREVIOUS_VERSION: dict[str, str] = {"1.7": "1.6"}

# Mods known to break on a version until they declare it (engine/runtime-level, not content).
KNOWN_RUNTIME_BREAKERS: dict[str, dict[str, str]] = {
    "1.7": {
        "zetrith.prepatcher": "Prepatcher's assembly reloader targets Unity's Mono runtime, which "
        "1.7 replaced; it breaks startup (menu without buttons). Disable it; mods that only used "
        "it as a Harmony provider work with brrainz.harmony.",
    }
}

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_environment() -> None:
    """Load local settings during application startup, never while importing pure modules."""
    load_dotenv(REPO_ROOT / ".env", override=False)


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser() if raw else default


@dataclass(frozen=True)
class Settings:
    mods_dir: Path | None
    db_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        mods_raw = os.getenv("RIMWORLD_TOOLS_MODS_DIR")
        return cls(
            mods_dir=Path(mods_raw).expanduser() if mods_raw else None,
            db_dir=_env_path("RIMWORLD_TOOLS_DB_DIR", REPO_ROOT / "bin" / "dbs"),
        )

    @property
    def cache_dir(self) -> Path:
        return self.db_dir / "cache"
