# Rimworld-Tools

A RimWorld-specific SteamCMD MCP server, plus (later) a Claude Skill for driving SteamCMD directly
when the server isn't enough.

## Running

```sh
make install    # uv sync
make start      # run the MCP server over stdio
make test       # pytest
make check      # ruff + black
make help       # list targets
```

Register with an MCP client:

```json
{
  "mcpServers": {
    "rimworld-tools": {
      "command": "uv",
      "args": ["run", "-m", "src.rimworld_tools.server"],
      "cwd": "C:\\Users\\sam\\Desktop\\Projects\\Rimworld-Tools"
    }
  }
}
```

## Configuration

All settings are env vars read by `src/rimworld_tools/config.py`; there is no config file.

| Var | Default | Purpose |
|---|---|---|
| `RIMWORLD_TOOLS_STEAMCMD_PREFIX` | `<repo>/bin` | Holds `steamcmd/` and `steam/` (the SteamCMD `force_install_dir`) |
| `RIMWORLD_TOOLS_MODS_DIR` | autodetected | Overrides RimWorld Mods folder discovery |
| `RIMWORLD_TOOLS_DB_DIR` | `<repo>/bin/dbs` | Synced community databases |
| `RIMWORLD_TOOLS_MAX_DOWNLOAD_ITEMS` | `50` | Cap on one `workshop_download` call |
| `STEAM_WEB_API_KEY` | unset | Enables key-gated tools; never returned in a tool result |

## Tools

None yet — Phase 0 (scaffold) is complete. See the implementation plan for the tool surface.

## Implementation notes

- **`modules/RimSort` is GPL-3.0 and read-only reference.** Never import, vendor, or copy from it.
  Knowledge was extracted clean-room into `docs/research/` (gitignored, local-only); consult those
  docs rather than re-reading RimSort source. Exact literals (command flags, API URLs, registry
  keys, log-line patterns, packageIds) are facts and are fine to use.
- `server.py` stays thin: `@mcp.tool` declarations and `main()` only. Real logic lives in siblings,
  one concern per file.
- Tools are `async def`; blocking work goes through `asyncio.to_thread` or
  `asyncio.create_subprocess_exec`.
- Docstrings are model-facing: one summary line, an optional caveat, then an `Example:` call.
- **Expected failures return `{"error": ..., "hint": ...}`; only genuine bugs raise.** Batch tools
  return `succeeded` and `failed[]` with per-item reasons rather than aborting on first failure.
- **No tool emits a warning the community databases can resolve** — resolve it first and return one
  actionable line (see the advisory layer).
- `from __future__ import annotations` everywhere; modern `X | None`.

### SteamCMD constraints worth not rediscovering

- **25 items max per invocation.** Beyond that SteamCMD's thread profiler overflows
  (`vprof.cpp: No room for new profile`) and downloads hang. Undocumented by Valve.
- **Its exit code is meaningless** — it returns 0 with per-item failures. Track a pending set and
  scrape `Success. Downloaded item <id>` / `ERROR! Download item <id>`.
- **On Windows its stdout doesn't stream through a pipe.** Tail `steamcmd/logs/console_log.txt` by
  byte offset instead.
- Downloads land at `<force_install_dir>/steamapps/workshop/content/294100/<pfid>/` with no flag to
  redirect them; a junction at that path pointing to the Mods folder avoids all post-processing.
