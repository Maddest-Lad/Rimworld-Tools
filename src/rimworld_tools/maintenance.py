from __future__ import annotations

import argparse
import asyncio
import json

from . import acf, cache, db, steamcmd
from .config import Settings, load_environment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RimWorld Tools maintenance commands")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("steamcmd-setup")
    setup.add_argument("--force-reinstall", action="store_true")
    setup.add_argument("--force-junction", action="store_true")
    commands.add_parser("depot-cache-clear")
    repair = commands.add_parser("acf-repair")
    repair.add_argument("--write", action="store_true")
    sync = commands.add_parser("db-sync")
    sync.add_argument("--force", action="store_true")
    sync.add_argument("sources", nargs="*")
    commands.add_parser("cache-clear")
    commands.add_parser("status")
    return parser


async def _run(args: argparse.Namespace, settings: Settings) -> dict:
    if args.command == "steamcmd-setup":
        return await steamcmd.setup(settings, args.force_reinstall, args.force_junction)
    if args.command == "depot-cache-clear":
        return steamcmd.clear_depot_cache(settings)
    if args.command == "acf-repair":
        return acf.repair(settings.acf_path, settings.workshop_content_dir, dry_run=not args.write)
    if args.command == "db-sync":
        return db.sync(settings, args.sources or None, args.force)
    if args.command == "cache-clear":
        return cache.Cache(settings.cache_dir).clear()
    return {"steamcmd": steamcmd.status(settings), "databases": db.status(settings)}


def main() -> None:
    args = _parser().parse_args()
    load_environment()
    print(json.dumps(asyncio.run(_run(args, Settings.from_env())), indent=2))


if __name__ == "__main__":
    main()
