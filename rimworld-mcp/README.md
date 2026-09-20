# RimWorld Tools

An MCP server for working with RimWorld mods and Steam Workshop content on Windows 10 LTSC.

Search the Workshop, manage subscriptions, inspect installed mods, and diagnose or sort your
active mod list. All Steam operations use the Steam Client API; Steam manages downloads and files.
Community databases supply dependency names, compatibility advisories and load-order rules.

## Setup

Install Python 3.12 or newer (64-bit), uv and make. Install the Steam edition of RimWorld, and
keep Steam online and signed in to an account that owns the game for Workshop operations.

From `rimworld-mcp/` (or `make install` at the workspace root):

```sh
make install  # install Python dependencies with uv
make config   # print MCP client registration snippets; writes no files
```

`make config` prints JSON for `mcp.json`, a Claude Code `mcp add` command, and Codex TOML.
The Claude command registers in project scope wherever you run it and uses the absolute
repository path to launch the server. Restart your MCP client after changing server code.

The server discovers the game's Steam API DLL automatically. No API key or SDK download is
needed. A short-lived helper connects as RimWorld, so Steam may briefly show it as running.
Windows 10 LTSC is the supported platform.

## Usage

Start with `environment_status()`, then search or inspect mods before subscribing. Use
`check_mod_updates()` to check installation and download state before sorting newly added mods.

| Tools | Purpose |
|---|---|
| `environment_status` | Discover the game and verify Steam readiness |
| `workshop_search`, `workshop_mod_info` | Find mods and inspect their metadata or descriptions |
| `resolve_workshop_url`, `collection_expand` | Resolve Workshop links and list collection members |
| `workshop_subscribe`, `workshop_unsubscribe` | Manage the signed-in account's subscriptions |
| `check_mod_updates` | Read live subscription, installation and download state |
| `list_installed_mods` | Inventory local, Steam, Git and official content, with active state |
| `modlist_enable`, `modlist_disable` | Activate or deactivate installed mods in `ModsConfig.xml` |
| `sort_modlist`, `diagnose_cycles` | Sort the active list or explain rule conflicts and missing dependencies |
| `modlist_snapshot`, `modlist_diff` | Save active-list snapshots and compare changes |

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
Its state is always live; it takes no cache-refresh argument.

`modlist_enable(ids)` and `modlist_disable(ids)` take packageIds or Workshop ids (up to 100) and
default to a dry run. Enabling appends to the end of the load order and reports requirements the
new mods still lack; disabling refuses Core, leaves files on disk, and names still-active mods that
depended on what was removed. Subscribing alone does not activate a mod.

Sorting defaults to a dry run. Every write snapshots the list first and refuses to edit
`ModsConfig.xml` while RimWorld is running; sorting additionally requires community load-order
rules, and a dependency cycle prevents writing. Local inventory, diagnostics, sorting, enabling and
snapshots remain usable without Steam, using existing community data when offline.

Local mod copies remain separate from Steam subscriptions. Select Steam copies in RimWorld and
review duplicates before removing local copies. No automatic migration or deletion occurs.

## Configuration and maintenance

Optional path settings can be supplied through environment variables or a local `.env` created
from `.env-template`. Existing environment variables take precedence.

| Variable | Default |
|---|---|
| `RIMWORLD_TOOLS_MODS_DIR` | Discovered RimWorld Mods folder |
| `RIMWORLD_TOOLS_DB_DIR` | `<repository>/bin/dbs` |

Community advisory data is prepared as needed. Maintenance commands stay out of the MCP tool list:

```sh
uv run -m src.rimworld_tools.maintenance status
uv run -m src.rimworld_tools.maintenance db-sync
uv run -m src.rimworld_tools.maintenance cache-clear
```

## Development

```sh
make start       # run the MCP server over stdio
make test        # pytest
make check       # Ruff and Black checks
make fix         # sync dependencies, auto-fix lint and format
make help        # list targets
```

This directory is the MCP server subproject of the RimWorld-Tools workspace; run the commands
above from `rimworld-mcp/`. The workspace root holds skills, `links/` and `.mcp.json`.
See [AGENTS.md](AGENTS.md) for architecture boundaries, implementation rules and secret handling.
