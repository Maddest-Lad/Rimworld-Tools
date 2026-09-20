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

# Real environment wins over .env so a shell export or MCP client `env` block can override it.
load_dotenv(REPO_ROOT / ".env", override=False)

STEAMCMD_BATCH_SIZE = 25


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser() if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    steamcmd_prefix: Path
    mods_dir: Path | None
    db_dir: Path
    max_download_items: int
    steam_web_api_key: str | None

    @classmethod
    def from_env(cls) -> Settings:
        mods_raw = os.getenv("RIMWORLD_TOOLS_MODS_DIR")
        return cls(
            steamcmd_prefix=_env_path("RIMWORLD_TOOLS_STEAMCMD_PREFIX", REPO_ROOT / "bin"),
            mods_dir=Path(mods_raw).expanduser() if mods_raw else None,
            db_dir=_env_path("RIMWORLD_TOOLS_DB_DIR", REPO_ROOT / "bin" / "dbs"),
            max_download_items=_env_int("RIMWORLD_TOOLS_MAX_DOWNLOAD_ITEMS", 50),
            steam_web_api_key=os.getenv("STEAM_WEB_API_KEY") or None,
        )

    @property
    def cache_dir(self) -> Path:
        return self.db_dir / "cache"

    @property
    def steamcmd_dir(self) -> Path:
        return self.steamcmd_prefix / "steamcmd"

    @property
    def steamcmd_exe(self) -> Path:
        return self.steamcmd_dir / "steamcmd.exe"

    @property
    def depotcache_dir(self) -> Path:
        return self.steamcmd_dir / "depotcache"

    @property
    def console_log(self) -> Path:
        return self.steamcmd_dir / "logs" / "console_log.txt"

    @property
    def force_install_dir(self) -> Path:
        return self.steamcmd_prefix / "steam"

    @property
    def workshop_dir(self) -> Path:
        return self.force_install_dir / "steamapps" / "workshop"

    @property
    def workshop_content_dir(self) -> Path:
        return self.workshop_dir / "content" / str(RIMWORLD_APP_ID)

    @property
    def acf_path(self) -> Path:
        return self.workshop_dir / f"appworkshop_{RIMWORLD_APP_ID}.acf"
