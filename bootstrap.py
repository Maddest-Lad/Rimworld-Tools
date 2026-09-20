"""Link the RimWorld folders into links/ and register the MCP server in .mcp.json.

Run through the server's environment so game discovery is shared with the MCP server:

    uv run --project rimworld-mcp python bootstrap.py [--dry-run] [--symlinks] [--force] [--no-db-sync]

Junctions are the default because they need no privilege on Windows 10 LTSC. Nothing under a
link target is ever touched: links are removed with rmdir/unlink only, never recursively.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MCP_DIR = ROOT / "rimworld-mcp"
LINKS_DIR = ROOT / "links"
MCP_JSON = ROOT / ".mcp.json"
SERVER_NAME = "rimworld-tools"

sys.path.insert(0, str(MCP_DIR))


@dataclass(frozen=True)
class LinkPlan:
    name: str
    target: Path
    provenance: str


def plan_links(discovered) -> list[LinkPlan]:
    """Turn the server's discovery result into the set of links to create.

    Saves and logs are derived from the config dir because discovery only validates Config/;
    Player.log lives in the LocalLow root itself, not a subfolder.
    """
    plans: list[LinkPlan] = []

    def add(name: str, found) -> None:
        if found is not None:
            plans.append(LinkPlan(name, Path(found.path), found.provenance))

    add("game", discovered.game_dir)
    add("mods", discovered.mods_dir)
    add("workshop", discovered.workshop_dir)
    add("config", discovered.config_dir)
    add("steam", discovered.steam_root)
    if discovered.config_dir is not None:
        locallow = Path(discovered.config_dir.path).parent
        plans.append(
            LinkPlan(
                "logs", locallow, "derived from config dir (Player.log lives here)"
            )
        )
        saves = locallow / "Saves"
        if saves.is_dir():
            plans.append(LinkPlan("saves", saves, "derived from config dir"))
    return plans


def merge_mcp_config(existing: dict | None, mcp_dir: Path) -> dict:
    """Add/replace our server entry and keep every other key untouched."""
    config = dict(existing or {})
    servers = dict(config.get("mcpServers") or {})
    servers[SERVER_NAME] = {
        "command": "uv",
        "args": ["--directory", str(mcp_dir), "run", "-m", "src.rimworld_tools.server"],
    }
    config["mcpServers"] = servers
    return config


def _is_link(path: Path) -> bool:
    # Junctions are reparse points but not symlinks; os.lstat exposes the attribute on Windows.
    if path.is_symlink():
        return True
    try:
        attrs = os.lstat(path).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def _link_target(path: Path) -> Path | None:
    try:
        return Path(os.path.realpath(path))
    except OSError:
        return None


def _remove_link(path: Path) -> None:
    # rmdir on a junction/dir symlink removes only the link; never rmtree here.
    if path.is_symlink() and not path.is_dir():
        path.unlink()
    else:
        os.rmdir(path)


def _create_link(link: Path, target: Path, symlinks: bool) -> None:
    if symlinks:
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                raise SystemExit(
                    "symlink creation needs Developer Mode or an elevated shell; "
                    "rerun without --symlinks to use junctions"
                ) from exc
            raise
        return
    import _winapi  # Windows only, stdlib

    _winapi.CreateJunction(str(target), str(link))


def apply_link(plan: LinkPlan, *, symlinks: bool, force: bool, dry_run: bool) -> str:
    link = LINKS_DIR / plan.name
    resolved_target = Path(os.path.realpath(plan.target))
    if link.exists() or link.is_symlink():
        if _is_link(link):
            if _link_target(link) == resolved_target:
                return "unchanged"
            if not force:
                return f"points elsewhere ({_link_target(link)}); use --force"
            if not dry_run:
                _remove_link(link)
        else:
            return "a real directory is in the way; not touching it"
    if dry_run:
        return "would create"
    _create_link(link, plan.target, symlinks)
    return "created"


def write_links_readme(plans: list[LinkPlan], statuses: dict[str, str]) -> None:
    lines = [
        "# links/",
        "",
        "Created by `make bootstrap`. Junctions into RimWorld and Steam folders.",
        "",
        "| Link | Target | Found via |",
        "|---|---|---|",
    ]
    for p in plans:
        lines.append(f"| `{p.name}` | `{p.target}` | {p.provenance} |")
    (LINKS_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mcp_json(dry_run: bool) -> str:
    existing = None
    if MCP_JSON.is_file():
        existing = json.loads(MCP_JSON.read_text(encoding="utf-8"))
    merged = merge_mcp_config(existing, MCP_DIR)
    if existing == merged:
        return "unchanged"
    if not dry_run:
        MCP_JSON.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return "would write" if dry_run else "written"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--dry-run", action="store_true", help="report without creating anything"
    )
    ap.add_argument(
        "--symlinks",
        action="store_true",
        help="use symbolic links instead of junctions",
    )
    ap.add_argument(
        "--force", action="store_true", help="replace links that point elsewhere"
    )
    ap.add_argument(
        "--no-db-sync", action="store_true", help="skip syncing community databases"
    )
    args = ap.parse_args(argv)

    from src.rimworld_tools import paths
    from src.rimworld_tools.config import load_environment

    load_environment()
    discovered = paths.discover()
    plans = plan_links(discovered)

    if not args.dry_run:
        LINKS_DIR.mkdir(exist_ok=True)
    statuses: dict[str, str] = {}
    width = max((len(p.name) for p in plans), default=4)
    print(f"RimWorld {discovered.version or '(version unknown)'}")
    for plan in plans:
        statuses[plan.name] = apply_link(
            plan, symlinks=args.symlinks, force=args.force, dry_run=args.dry_run
        )
        print(f"  {plan.name:<{width}}  {statuses[plan.name]:<40}  {plan.target}")
    if not args.dry_run:
        write_links_readme(plans, statuses)

    print(f"  {'.mcp.json':<{width}}  {write_mcp_json(args.dry_run)}")

    if not args.no_db_sync and not args.dry_run:
        print("Syncing community databases...")
        subprocess.run(
            ["uv", "run", "-m", "src.rimworld_tools.maintenance", "db-sync"],
            cwd=MCP_DIR,
            check=False,
        )

    if discovered.game_dir is None:
        print(
            "RimWorld was not found. Install the Steam edition, or set RIMWORLD_TOOLS_MODS_DIR "
            "in rimworld-mcp/.env",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
