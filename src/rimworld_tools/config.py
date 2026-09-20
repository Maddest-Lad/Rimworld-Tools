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
