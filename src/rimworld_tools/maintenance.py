from __future__ import annotations

import argparse
import asyncio
import json

from . import cache, db, paths, steam_transport
from .config import Settings, load_environment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RimWorld Tools maintenance commands")
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("db-sync")
    sync.add_argument("--force", action="store_true")
    sync.add_argument("sources", nargs="*")
    commands.add_parser("cache-clear")
    commands.add_parser("status")
    return parser


async def _run(args: argparse.Namespace, settings: Settings) -> dict:
    if args.command == "db-sync":
        return await asyncio.to_thread(db.sync, settings, args.sources or None, args.force)
    if args.command == "cache-clear":
        return await asyncio.to_thread(cache.Cache(settings.cache_dir).clear)
    return {
        "steam": await steam_transport.request(settings, "probe"),
        "rimworld": (await asyncio.to_thread(paths.discover, settings)).to_dict(),
        "databases": await asyncio.to_thread(db.status, settings),
    }


def main() -> None:
    args = _parser().parse_args()
    load_environment()
    print(json.dumps(asyncio.run(_run(args, Settings.from_env())), indent=2))


if __name__ == "__main__":
    main()
