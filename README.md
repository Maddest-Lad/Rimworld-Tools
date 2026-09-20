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

Start the server from the repository root. All Workshop operations require 64-bit Python, the
Windows Steam edition of RimWorld, and Steam running, online and signed in to an account that owns it.
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
Repeated requests return `already_satisfied` ids without dispatching another change.

`workshop_mod_info(pfids, include_description=True)` requests the long description from Steam.
Descriptions are omitted by default, including on cache hits. The native API has an 8,000-byte
buffer; `description_may_be_truncated` flags results near that limit. Missing/private items are
reported as unavailable, not assumed to be unpublished.

Metadata and collection membership are cached for 6h; searches for 1h. Caches are versioned and
scoped to the signed-in Steam account, with separate compact/description variants. Even cache
reads verify the current account through Steam. `refresh=True` bypasses the application cache and
queries Steam again. Partial failures are not cached.

`check_mod_updates(pfids=None)` returns live subscription, installation and download state.
`outdated` contains installed Steam copies marked as needing updates; pending installs and ids
not subscribed are reported separately. `installed_at` is Steam's installation timestamp.
This tool no longer takes `include_steam_client` or `refresh`; its state is always live.

Community advisory data is prepared as needed. Maintenance commands stay out of the MCP tool list:

```sh
uv run -m src.rimworld_tools.maintenance status
uv run -m src.rimworld_tools.maintenance db-sync
uv run -m src.rimworld_tools.maintenance cache-clear
```

Steam Client API is the sole Steam backend: Steam Web API and SteamCMD code, API-key settings,
setup and repair commands have been removed. Community databases still download from GitHub.
Only `RIMWORLD_TOOLS_MODS_DIR` and `RIMWORLD_TOOLS_DB_DIR` remain as optional path settings.

Existing SteamCMD-downloaded mods remain discoverable as local copies; nothing is migrated or
deleted automatically. The `steamcmd` inventory source and ACF-derived `timeupdated` field have
been removed. Select the Steam copies in RimWorld and review duplicates before removing local
copies. Subscription tools never edit Steam's manifests or remove mod directories themselves.
Local inventory, diagnostics, sorting and snapshots remain usable without Steam, using existing
community data when offline.

Sorting writes require current community load-order rules and refuse to edit `ModsConfig.xml`
while RimWorld is running. Read-only analysis remains available when either condition is not met.

Run `make config` to print ready-to-paste snippets for `mcp.json`, a self-contained Claude Code command, and Codex.
