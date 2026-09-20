# RimWorld Tools

An MCP server for working with RimWorld mods and Steam Workshop content on Windows 10 LTSC.

It discovers the local game and Steam libraries, subscribes and unsubscribes through the Steam
client, leaves Workshop downloads and file management to Steam, inventories mods,
checks metadata and updates, and analyzes or sorts the active mod list. RimSort is a read-only
reference submodule; none of its code is imported or executed.

The supported environment is Windows 10 LTSC. The path and filesystem boundaries are kept small
enough to support other systems later, but other platforms are not currently implemented.

## Setup

```sh
make submodules  # init/update the RimSort submodule
make install      # uv sync
```

Start the server from the repository root. Subscription changes require 64-bit Python, the
Windows Steam edition of RimWorld, and Steam running and signed in to an account that owns it.
The native Steam API DLL is discovered in the installed game; no SDK download or credentials
are needed. A short-lived helper connects as RimWorld, so Steam may briefly show it as running.

## Usage

```sh
make start   # run the MCP server over stdio
make lint    # ruff check
make format  # black --check
make fix     # auto-fix lint + format
```

`environment_status()` provides a compact read-only view of game discovery and Steam availability.
`workshop_subscribe(pfids)` and `workshop_unsubscribe(pfids)` accept up to 50 Workshop ids and return
per-item results. Subscribe validates that the items belong to RimWorld. Success confirms the
subscription change; Steam downloads asynchronously and removes unsubscribed files after the
game exits. Wait for downloads to finish before inventorying or sorting newly subscribed mods.
An unsubscribe for an item Steam does not report as subscribed returns a per-item failure.

`workshop_mod_info(pfids, include_description=True)` includes the full Steam BBCode description.
Descriptions are omitted by default, including on cache hits. Old cache entries are refreshed
when a description is first requested.

Community advisory data is prepared as needed. Maintenance commands stay out of the MCP tool list:

```sh
uv run -m src.rimworld_tools.maintenance status
uv run -m src.rimworld_tools.maintenance db-sync
```

The old `workshop_download` and `workshop_delete` MCP tools have been removed. Existing SteamCMD
copies remain visible in inventory and update checks, and the old maintenance code remains for
those installations. Subscribing does not migrate or delete copies in RimWorld's local Mods
folder. Select the Steam copies in RimWorld and review duplicate copies before removing them.
Subscription tools never edit Steam's ACF files or remove mod directories themselves.

Sorting writes require current community load-order rules and refuse to edit `ModsConfig.xml`
while RimWorld is running. Read-only analysis remains available when either condition is not met.

Run `make config` to print ready-to-paste snippets for `mcp.json`, a self-contained Claude Code command, and Codex.
