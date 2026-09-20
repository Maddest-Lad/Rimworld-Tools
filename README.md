# RimWorld Tools

An MCP server for working with RimWorld mods and Steam Workshop content on Windows 10 LTSC.

It discovers the local game and Steam libraries, installs SteamCMD on demand for Workshop
downloads, links SteamCMD's Workshop output to the RimWorld Mods directory, inventories mods,
checks metadata and updates, and analyzes or sorts the active mod list. RimSort is a read-only
reference submodule; none of its code is imported or executed.

The supported environment is Windows 10 LTSC. The path and filesystem boundaries are kept small
enough to support other systems later, but other platforms are not currently implemented.

## Setup

```sh
make submodules  # init/update the RimSort submodule
make install      # uv sync
```

Start the server from the repository root. The first `workshop_download` automatically prepares
SteamCMD and its safe junction after locating the Mods directory. It refuses to replace an
existing non-empty directory or a junction pointing elsewhere.

## Usage

```sh
make start   # run the MCP server over stdio
make lint    # ruff check
make format  # black --check
make fix     # auto-fix lint + format
```

`environment_status()` provides a compact read-only view of discovery and SteamCMD readiness.
Normal MCP operations prepare SteamCMD and community advisory data as needed. Exceptional repair
actions stay out of the MCP tool list and are available through:

```sh
uv run -m src.rimworld_tools.maintenance status
uv run -m src.rimworld_tools.maintenance db-sync
uv run -m src.rimworld_tools.maintenance acf-repair --write
uv run -m src.rimworld_tools.maintenance depot-cache-clear
```

Sorting writes require current community load-order rules and refuse to edit `ModsConfig.xml`
while RimWorld is running. Read-only analysis remains available when either condition is not met.

Run `make config` to print ready-to-paste snippets for `mcp.json`, Claude Desktop, and Codex.
