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

## Secrets — never read `.env`

**Never open, read, cat, grep, print, or otherwise view `.env`** (or any `.env.*` file). It holds
`STEAM_WEB_API_KEY`. This applies to every tool: Read, Bash, Grep, Glob output, subagents — all of
them. If a task seems to need the key's value, it doesn't: the code reads it from the environment and
never returns it. If `.env` shows up in a diff, `git status`, or an error message, do not inspect its
contents. `.env-template` is the only env file that may be read or edited.

## Configuration

All settings are env vars read by `src/rimworld_tools/config.py`. A `.env` at the repo root is
loaded on startup (copy `.env-template`); variables already set in the environment take precedence.

| Var | Default | Purpose |
|---|---|---|
| `RIMWORLD_TOOLS_STEAMCMD_PREFIX` | `<repo>/bin` | Holds `steamcmd/` and `steam/` (the SteamCMD `force_install_dir`) |
| `RIMWORLD_TOOLS_MODS_DIR` | autodetected | Overrides RimWorld Mods folder discovery |
| `RIMWORLD_TOOLS_DB_DIR` | `<repo>/bin/dbs` | Synced community databases |
| `RIMWORLD_TOOLS_MAX_DOWNLOAD_ITEMS` | `50` | Cap on one `workshop_download` call |
| `STEAM_WEB_API_KEY` | unset | Enables key-gated tools; never returned in a tool result |

## Tools

| Tool | Purpose |
|---|---|
| `rimworld_locate()` | Find game, Mods, config and Workshop dirs, each with provenance |
| `steamcmd_status()` | Health check: installed? junction OK? ACF item count? Steam running? |
| `steamcmd_setup(force_reinstall, force_junction)` | Install SteamCMD + junction its output dir to Mods. Idempotent |
| `workshop_download(pfids, validate, clear_depot_cache)` | Download/update mods into Mods. Blocks; batches of 25; per-item results |
| `clear_depot_cache()` | First remediation for downloads that succeed but write nothing |
| `acf_repair(dry_run=True)` | Drop ACF entries with no directory on disk. Refuses while steamcmd.exe runs |
| `workshop_mod_info(pfids)` | Title/updated/size/tags/unpublished from the Workshop. Keyless, 300/chunk |
| `check_mod_updates(pfids?, include_steam_client=True)` | Local ACF timestamp vs Workshop; returns the outdated list |
| `collection_expand(url_or_id)` | Mod pfids inside a collection (nested collections filtered) |
| `resolve_workshop_url(url)` | Pasted URL/id → `{pfid, kind: mod\|collection\|unpublished}` |
| `workshop_search(query?, limit, game_version?, include_translations, include_scenarios, sort, days)` | Workshop search. Defaults: `Mod` + installed version tag (e.g. `1.6`), Translation/Scenario excluded. `sort`: relevance\|trend\|recent\|top\|updated. Needs `STEAM_WEB_API_KEY`, else returns an equivalent browse URL |
| `workshop_delete(pfids)` | Remove dir + both ACF sections + depot manifest, so re-download really downloads |

Typical first session: `rimworld_locate` → `steamcmd_setup` → `workshop_download([...])`.

Steam's `QueryFiles` text search *ranks* rather than filters — a nonsense query still reports `total`
in the tens of thousands. `workshop_search` adds a hint when no returned title contains a query word;
`total` is never a match count. Tag filters (`requiredtags`/`excludedtags`) do genuinely filter.

ACF write guards only wait on `steamcmd.exe`. The Steam client rewrites *its own* ACF, never ours, and it
is usually running — guarding on `steam.exe` would make every write tool permanently refuse.

Layout under the prefix (`bin/` by default):

```
bin/steamcmd/            SteamCMD itself; steamcmd.exe is tracked, the rest is gitignored
bin/steam/               force_install_dir — gitignored, contains a junction into the real Mods dir
  steamapps/workshop/appworkshop_294100.acf
  steamapps/workshop/content/294100  -> <RimWorld>/Mods   (NTFS junction)
```

`workshop_delete` purges BOTH ACF sections and the `depotcache/294100_<manifest>.manifest`
file, or SteamCMD will silently refuse to re-download the item.

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
