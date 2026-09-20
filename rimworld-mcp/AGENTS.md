# rimworld-mcp

The RimWorld MCP server for Windows 10 LTSC, a subproject of the Rimworld-Tools workspace
(the parent directory holds the workspace `CLAUDE.md`, skills, `links/` and `.mcp.json`). Steam Client API owns Workshop queries and
subscriptions; local modules handle inventory, advisories, modlists and sorting.

## Running

```sh
make install    # uv sync
make config     # print registration snippets without writing files
make start      # run the MCP server over stdio
make test       # pytest
make check      # ruff + black
make help       # list targets
```

Use `make config` for registration snippets using the current repository path. Keep the server
entry point `src.rimworld_tools.server` compatible with those snippets.

## Secrets — never read `.env`

**Never open, read, cat, grep, print, or otherwise view `.env`** (or any `.env.*` file).
It may contain secrets retained from earlier versions. This applies to every tool and agent.
Never inspect its contents in diffs or error messages. `.env-template` is the only env file that
may be read or edited. No Steam API key is needed or consumed by this project.

## Configuration

All settings are env vars read by `src/rimworld_tools/config.py`. A `.env` at the repo root is
loaded on startup (copy `.env-template`); variables already set in the environment take precedence.

| Var | Default | Purpose |
|---|---|---|
| `RIMWORLD_TOOLS_MODS_DIR` | autodetected | Overrides RimWorld Mods folder discovery |
| `RIMWORLD_TOOLS_DB_DIR` | `<rimworld-mcp>/bin/dbs` | Synced community databases |

## Tools

| Tool | Purpose |
|---|---|
| `environment_status()` | Game discovery and verified Steam client readiness |
| `workshop_subscribe(pfids)` | Subscribe the signed-in Steam user; Steam downloads asynchronously |
| `workshop_unsubscribe(pfids)` | Unsubscribe; Steam handles removal, local Mods copies remain untouched |
| `list_installed_mods(source?, package_ids?, detail, include_invalid)` | Every mod on disk: packageId, name, source (ludeon\|steam\|git\|local), pfid, version_ok, active. Compact by default; `detail` adds paths/deps/load rules |
| `workshop_mod_info(pfids, refresh=False, include_description=False)` | Native Workshop metadata; optional descriptions with possible-truncation flag; 50/chunk |
| `check_mod_updates(pfids?)` | Live subscription/install/download state; outdated lists installed items needing updates |
| `collection_expand(url_or_id)` | Mod pfids inside a collection (nested collections filtered) |
| `resolve_workshop_url(url)` | Pasted URL/id → `{pfid, kind: mod\|collection\|other\|other_game\|unknown}` |
| `workshop_search(query?, limit, game_version?, include_translations, include_scenarios, sort, days)` | Workshop search. Defaults: `Mod` + installed version tag (e.g. `1.6`), Translation/Scenario excluded. `sort`: relevance\|trend\|recent\|top\|updated. Requires the signed-in, online Steam client; no web fallback |
| `modlist_enable(ids, dry_run=True)` / `modlist_disable(ids, dry_run=True)` | Activate/deactivate by packageId or pfid (≤100). Enable appends at the end and reports what the new mods still lack; disable refuses Core and names still-active dependants. Writes snapshot first |
| `sort_modlist(dry_run=True)` | 4-tier topological load order for ModsConfig.xml. A write snapshots first; a cycle writes nothing |
| `diagnose_cycles()` | Cycles with per-edge rule sources, incompatible active pairs, missing/inactive dependencies |
| `modlist_snapshot(note, list_only)` | Save or list snapshots of the active list (`bin/dbs/modlists/`) |
| `modlist_diff(old="latest", new="current")` | Added/removed/moved between `current`, `latest`, or a snapshot id |

Typical first session: `environment_status` -> `workshop_subscribe([...])` -> wait for Steam downloads.
All Workshop operations use the installed game's `steam_api64.dll` in a short-lived helper.
They require 64-bit Python and an online, signed-in Steam client. Never edit Steam's manifests or
remove its Workshop directories. Success confirms subscription state, not download completion.
The helper targets UGC v016 / Utils v010 / User v021; unsupported exports fail clearly.

Steam Client API is the only Steam backend. No Web API, API-key setup, SteamCMD installation,
junction creation or legacy repair path remains. `maintenance` retains status, database sync and
cache clearing. HTTP requests remain only for community database downloads.

Search uses native enum values (relevance=11, updated=19), which differ from Web API values.
Queries page at 50 items, search is capped at 100 results, and trend days must be 1-365.
Search ranking/total is not an exact textual match count; preserve the nonmatch hint.

Existing downloaded Mods folders are local copies, not proof of SteamCMD provenance. Keep their
Workshop ids and respect `_steam` selection. Do not apply a Steam copy's update state to a local
copy with the same id. No legacy runtime directories or user mod files are migrated automatically.

## Implementation notes

### Module boundaries

| Module | Responsibility |
|---|---|
| `server.py` | MCP declarations and startup |
| `runtime.py` | Settings, mutation coordination and community database preparation |
| `workshop.py`, `subscriptions.py` | Tool results, validation and advisory composition |
| `workshop_queries.py`, `cache.py` | Account-scoped metadata/search caching and freshness |
| `steam_transport.py` | Structured helper requests, output validation, timeouts and process cleanup |
| `steam_client.py`, `steam_types.py` | Native bindings, ABI layouts, session/query handles and callbacks |
| `workshop_ids.py` | Shared id validation and Workshop URL parsing |
| `paths.py`, `mods.py` | Windows discovery, local inventory and About.xml parsing |
| `modlist.py`, `sorting.py` | Selected-copy resolution, snapshots, enable/disable, guarded writes and pure sorting |
| `db.py`, `advisories.py` | Community data synchronization and actionable advisories |
| `filesystem.py`, `processes.py`, `locking.py` | Small Windows filesystem, process and locking utilities |
| `maintenance.py` | Explicit status, database sync and cache clearing commands |

### Working rules

- **RimSort (GPL-3.0) is reference only.** Never import, vendor, or copy from it. Knowledge was
  extracted clean-room into `docs/research/` (gitignored, local-only); consult those docs. Exact literals (command flags, API URLs, registry
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
- Use discrete commits and lightweight comments explaining constraints rather than restating code.
- Test native mutations with mocks. Live subscription changes require a specifically authorized
  item; do not use the user's existing modlist as a mutation test fixture. Keep read-only integration
  checks separate from ordinary tests and report which checks were actually run.
- Never expose native stdout on the MCP stream. Reap owned helpers on timeout/cancellation, release
  query handles, and distinguish confirmed changes from uncertain outcomes.

### About.xml parsing (`mods.py`)

- `PackageId` is a lowercasing `str` subclass; every rule list and index is case-insensitive.
- Parse order: strict ElementTree → escape bare `&`/`<` and retry → BeautifulSoup `lxml-xml`. The
  escape pass exists because lxml's recovery *truncates* at a stray `<`, silently dropping every
  field after it. Real descriptions contain things like "takes < 10s".
- `*ByVersion` blocks **replace** the base list when the game's `major.minor` matches (an empty
  block means "none", not "fall back"); `forceLoadAfter`/`forceLoadBefore` are always appended.
- `supportedVersions` is normalised to `major.minor` at parse time; `version_ok` compares
  normalised values. Official DLC About.xml omits `<name>` — `DLC_NAMES` fills it.
- Classification checks `PublishedFileId.txt == folder name` **before** `.git`, because some
  Workshop items ship a stray `.git` directory.
- Dependencies read `steamWorkshopUrl` (RimSort reads `workshopUrl`, which is a bug; accepted as alias).

### Community databases and advisories (`db.py`, `advisories.py`)

Synced into `bin/dbs/<name>/` from GitHub zips. Branches differ and are a 404 hazard:
`RimSort/*` are `main`, `emipa606/*` are `master` (sync falls back to the other on 404).

| DB | Trusted for |
|---|---|
| Steam Workshop DB (`steamDB.json`, ~48MB, ~58k entries) | packageId↔pfid mapping, display names, `blacklist` comments, dependency names |
| Community Rules | `loadAfter`/`loadBefore`/`loadTop`/`loadBottom` |
| Use This Instead (`replacements.json.gz`, a **list** keyed by `oldWorkshopId`) | "abandoned → maintained fork" |
| No Version Warning (**versioned subdirs only**, `1.6/ModIdsToFix.xml`; no root file) | suppressing false `version_mismatch` |

**Never trust the Steam DB's `unpublished` flag.** It can lag republishing. Native lookup failure
is also not proof of unpublishing: return the per-item failure reason. Local inventory never emits
unpublished advisories. Successful native metadata can receive blacklist/replacement advisories.

Advisories are `{kind, severity, message, action?}` with kinds `version_mismatch` (suppressed
outright when No Version Warning lists the mod), `replaced`, `unpublished`, `blacklisted`,
`missing_dependency` (named via the Steam DB with a ready `workshop_subscribe` action). A missing DB
produces one top-level `notice` per response, never one per mod, and never an error.

### Native query cache (`workshop_queries.py`, `cache.py`)

Metadata/collection records have a 6h TTL; search records a 1h TTL. Namespaces include a schema
version and the current Steam account. Description and children variants are separate. Account
identity is verified even before cached reads; failures/private data must not cross account scope.
Failures are never cached; a partial batch caches only successful items. `refresh=true` bypasses
our cache and native queries disable Steam's optional cached response allowance. Results retain
cache provenance. Subscription and installation state is always live. Database ETags are separate.

Long descriptions use the SDK's fixed 8,000-byte buffer; flag possible truncation near its limit.
Do not promise unlimited descriptions or fall back to scraping Workshop pages.

### Load-order sorting (`sorting.py`, `modlist.py`)

`sorting.sort` is a pure function: partition active mods into four tiers, topologically sort each
tier alone, concatenate. Tier 0 = Core/DLC/Harmony/Prepatcher (`TIER_ZERO`), tier 1 = known
frameworks (`TIER_ONE`) + community `loadTop`, tier 3 = `loadBottom`, tier 2 = the rest. Tiers 0/1
absorb their transitive *dependencies*; tier 3 absorbs its transitive *dependants*. Ties within a
topological level break on lowercased display name. Verified against a real 288-mod RimSort-sorted
list: identical except one same-level framework tie.

Edges are `after -> before -> {sources}` with sources `about:<pid>`, `community`, `user`, unioned
exactly as RimSort does (no override). Our extension: `userRules.json` accepts `removeLoadAfter` /
`removeLoadBefore` per mod to drop an edge a lower layer added — that is how a reported cycle gets
fixed. A cycle in any tier aborts the whole sort and nothing is written; `diagnose_cycles` returns
each cycle's edges with their sources.

`ModsConfig.xml` entries may carry a `_steam` suffix (RimWorld's "use the Workshop copy" marker);
it is preserved on write. Ids that resolve to no installed mod are kept at the end, never dropped.
RimWorld itself writes bare lowercased ids and adds `_steam` only when a local copy shares the
packageId (verified on a 311-entry list: zero suffixes); `modlist_enable` does the same.

Every `ModsConfig.xml` write (`sort_modlist`, `modlist_enable`, `modlist_disable`) goes through
`modlist._write_blocked` (refuses while RimWorld runs or if the file changed since it was read) and
`modlist._commit` (snapshot, then atomic replace), under `runtime.mutation("modlist")`.
