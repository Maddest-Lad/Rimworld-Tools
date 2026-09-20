# Steam Client API consolidation plan

Status: planned; implementation has not started.

## Objective and decisions

Use the Steam Client API as the only Steam backend. Remove Steam Web API and SteamCMD
implementations, configuration, dependencies that become unused, and maintenance commands.
Windows 10 LTSC, 64-bit Python, and the installed Steam edition of RimWorld are the supported
environment. Steam must be running and signed in for live Workshop operations.

Keep local mod discovery, About.xml parsing, modlist analysis, sorting, snapshots, and community
databases. Community database downloads from GitHub remain: removing the Steam Web API does not
mean removing all HTTP access. No automatic Web API or SteamCMD fallback will remain.

Preserve user files. Do not move, subscribe, unsubscribe, or delete existing mods as part of this
code migration. Existing SteamCMD-downloaded folders remain discoverable as local mods. Remove
tracked SteamCMD assets from the project, but leave untracked installations, manifests, junctions,
caches, and the user's secret files untouched. Keep ignore rules protecting old runtime folders.

No further product decision is needed to begin. The technical checks below are implementation
gates; a failed check should produce a specific finding, not a silent return to the old backends.

## Current evidence

- MCP subscription tools already use a short-lived native helper. Read-only initialization
  succeeded against the installed RimWorld DLL; real subscription mutations have not been tested.
- The installed DLL exports UGC details, search, collection children, full-description options,
  subscription enumeration, item state, installation information, and download information.
  Export presence is not proof of query behavior or ABI correctness.
- Subscription preflight still uses the Web API, so a subscription currently depends on both APIs.
- `workshop.py` still imports SteamCMD for ID normalization and retains its old deletion code.
- SteamCMD setup/repair remains in `maintenance.py`, and its settings remain in `config.py`.
- `mods.py` and `workshop.py` duplicate ACF timestamp discovery. Both let a legacy copy overwrite
  the timestamp for a Steam copy with the same Workshop id.
- The current inventory labels local Workshop copies as `steamcmd` based on PublishedFileId.txt,
  which does not establish that SteamCMD created them.
- The baseline is 182 passing tests plus clean Ruff and Black checks.

## Intended boundaries

| Component | Responsibility |
|---|---|
| `server.py` | Thin MCP declarations and startup |
| `workshop.py` | Workshop operations, shared ID validation, result normalization, cache and advisory composition |
| `steam_client.py` | Explicit native bindings, Steam session, query handles and callback results |
| One helper transport module | Launch/reap the native helper, structured requests/results, bounded execution and output isolation |
| `runtime.py` | Settings, operation coordination and automatic prerequisite checks |
| `mods.py` / `paths.py` | Local inventory, actual copy identity and Windows discovery |
| `cache.py` | Versioned metadata cache with freshness and account boundaries |

Evolve the existing subscription modules into these roles. Do not add a generic backend interface,
provider registry, arbitrary native-call dispatcher, or parallel implementations of each operation.
Keep the helper short-lived initially: one initialized session per batch or query operation,
including its required pages. Do not introduce a permanent background service without measured need.

## Commit 1 — Establish the shared client session and query primitives

Suggested commit: `refactor: centralize Steam client sessions and queries`

- Consolidate validation of positive unsigned 64-bit Workshop ids and URL parsing outside the
  legacy backends. Reject booleans, invalid ids and overflow; deduplicate while preserving order.
- Give the helper a small explicit operation protocol. Use structured input for search strings,
  filters and batches; never build shell commands from them.
- Bind the installed DLL's supported interfaces with explicit argument types, return types,
  structure packing and callback ids. Fail clearly on unsupported DLL versions or architecture.
- Verify application identity and signed-in/online state as needed. Do not claim readiness solely
  from the presence of steam.exe or the DLL. Keep local-only tools independent of Steam readiness.
- Add reusable callback waiting and query-handle cleanup. Release every query handle on success,
  error or cancellation, shut down initialized sessions, and bound both query and helper execution.
- Keep native output isolated from MCP stdout. Validate helper result shape and reap owned
  processes on timeout/cancellation/crash; return uncertain mutation outcomes honestly.
- Reuse the existing mutation lock across processes. Do not serialize independent metadata reads
  behind long mutations unless the actual Steam session architecture requires it.

Validation: ABI/layout tests; helper protocol and failure tests; read-only initialization and a
known-item details query against the installed DLL. Verify no mod or subscription mutation occurs.

## Commit 2 — Move metadata, descriptions, collections and URL resolution

Suggested commit: `feat: query Workshop metadata through the Steam client`

- Implement batched details queries and map results to the existing compact metadata shape.
- Preserve `workshop_mod_info(..., include_description=False)` and `refresh`. Request long
  descriptions only when needed. Verify the SDK's actual buffer limits and encoding; never label
  truncated text as a full description. Report a limitation explicitly if the native API imposes one.
- Resolve collection children through query results. Distinguish collection members from mod
  dependencies using the parent item type; continue filtering nested collections from expansion.
- Resolve URLs locally to ids, then use queried item type to distinguish mods and collections.
  Distinguish unavailable/private/not-found results from transport or session failures. Remove HTML
  page-sentinel scraping; do not claim an item is unpublished merely because a query failed.
- Preserve partial batch results with per-item failures and actionable hints.
- Version the metadata cache so old Web API records cannot masquerade as native query results.
  Keep description completeness explicit so a compact cache hit cannot satisfy a rich request.
- Partition account-dependent/private results by Steam account and app. Never cache transient
  failures as unavailable items. Do not serve another account's cached private data if signed out.
  Keep subscription/download state live, separate from the metadata TTL.

Validation: known public mod, long/non-ASCII description, collection with nested children, invalid
and unavailable ids, partial failures, refresh, cache completeness and account isolation. Compare
the important returned fields with expected fixtures; no runtime fallback to the Web API.

## Commit 3 — Move Workshop search

Suggested commit: `feat: search Workshop through the Steam client`

- Implement native query creation, search text, required/excluded tags, sorting and pagination.
- Preserve the current public search arguments, installed-version filtering, Mod tag, and optional
  exclusion of translations/scenarios. Verify each exposed sort maps to a supported native mode.
- Respect native page sizes while filling the requested limit. Bound pagination and release query
  handles after use. Validate native parameter limits such as trend days before submitting calls.
- Remove API-key gating and the missing-key browse fallback. Missing Steam readiness gets one
  concrete error/hint; it must not prevent the MCP server from starting or listing tools.
- Retain the existing caution that search ranking/total is not an exact textual-match count unless
  native behavior is demonstrated otherwise. Preserve useful cache provenance.

Validation: keyword and empty-query modes, each sort, required/excluded tags, limits spanning pages,
no matches, failed later pages, query cleanup, and read-only searches on the installed client.

## Commit 4 — Unify subscription validation and installation state

Suggested commit: `refactor: use Steam client state for Workshop operations`

- Move subscription preflight to the native details query in the same helper session as mutations.
  Validate RimWorld ownership of items, item type and per-item eligibility before dispatch.
- Use account/app-scoped subscription enumeration to establish state. Make repeated subscribe and
  unsubscribe requests idempotent with explicit already-satisfied results. An unavailable or
  uninitialized local state must not be interpreted as proof that an item is unsubscribed.
- Support removing a subscribed item that is no longer publicly queryable without requiring a
  successful public metadata lookup. Do not allow cross-game subscription changes.
- Confirm each dispatched mutation through its call result. Distinguish rejected, confirmed,
  already-satisfied and uncertain outcomes; success never implies download completion.
- Use subscription enumeration, item state, install information and download progress for Steam
  items. Replace ACF-derived update state with explicit installed/needs-update/downloading/pending
  states. Explain any changed timestamp semantics instead of relabeling native fields incorrectly.
- Keep `check_mod_updates` as the existing entry point; remove `include_steam_client`, which is
  meaningless with a single Steam backend. Report ids not subscribed or not installed separately.
- Keep filesystem inventory available offline. Local copies stay tied to their own paths; never
  assign the Steam copy's installation timestamp or update status to a local duplicate.
- Update environment status with meaningful Steam capability results. Keep it read-only and do not
  create a separate setup MCP tool.

Validation: mocked per-item mutation results, already-satisfied requests, deleted subscribed items,
wrong-app ids, offline state, timeout/cancellation, pending downloads, and local/Steam duplicates.
Read-only integration checks compare native subscription/install state with filesystem inventory.
A real subscribe/unsubscribe round trip requires a specifically chosen user-authorized item; do
not use the user's existing modlist as a mutation test fixture. Report if that check remains unrun.

## Commit 5 — Remove obsolete implementations and configuration

Suggested commit: `refactor: remove Steam Web API and SteamCMD backends`

- Delete `webapi.py`, `steamcmd.py`, old Workshop deletion/depot helpers, and their obsolete tests.
  Move any still-useful pure parsing or validation before deleting its previous module.
- Remove SteamCMD setup, depot clearing and ACF repair commands. Maintenance retains database sync,
  cache clearing and current environment/database status.
- Remove the Web API key, SteamCMD prefix and download-cap settings, their derived paths, and
  SteamCMD-specific constants from settings and `.env-template`. Keep dotenv only for remaining
  optional path settings. Never inspect, rewrite or delete the user's `.env`.
- Remove SteamCMD-specific inventory provenance. Keep local Workshop ids as metadata, classify
  local copies as local/git as appropriate, and retain correct `_steam` copy selection in modlists.
- Remove unused ACF mutation/repair code. Move process detection to a small appropriate helper.
  Retain VDF library discovery and only any independently justified read-only manifest parsing.
- Remove junction creation and SteamCMD-specific filesystem code. Preserve the safe filesystem
  deletion utility used by community database staging; do not delete `symlink.py` wholesale without
  accounting for those callers. Rename/extract the retained utility if that clarifies its purpose.
- Remove the tracked SteamCMD executable and any obsolete lockfile/package dependencies. Retain
  `requests` for community database downloads and `vdf` for Steam library discovery if still used.
- Preserve ignored legacy directories and the pre-existing untracked `bin/.rimworld-tools.lock`.

Validation: repository-wide reference scan excluding secrets and the read-only RimSort submodule;
no executable Web API/SteamCMD path, no key in tool schemas/settings, no writes to Steam manifests
or mod directories, and no dead maintenance commands. Review dependency/lockfile changes together.

## Commit 6 — Update the contract and complete regression checks

Suggested commit: `docs: document the Steam client-only workflow`

- Update README, AGENTS, tool docstrings, settings examples and maintenance help together.
- Mark the earlier architecture review as historical where its backend assumptions are superseded.
- Explain Steam availability requirements, the helper's possible brief in-game presence, asynchronous
  downloads, cached metadata behavior and private/unavailable results.
- Document the source-label and update-result changes and how existing local copies remain visible.
  Do not promise automatic migration or deletion. Keep comments limited to non-obvious constraints.
- Verify `make config` still launches the same MCP module from its absolute repository location;
  configuration output should contain no Steam credentials or obsolete setup requirements.

Validation: full suite, Ruff, Black, MCP schema/description inspection, config output and read-only
native integration checks. Remove tests solely for deleted behavior while retaining independent
coverage for parsing, advisories, sorting, copy selection, cache isolation and safe database staging.

## Completion criteria

- Exactly one Steam backend; no Web API/SteamCMD fallback or unused legacy implementation.
- No Steam API key setup and no manual MCP environment preparation.
- Existing Workshop tools use native queries with deliberate, documented contract changes only.
- Optional descriptions work without bloating default results or leaking across cache/account scope.
- Steam owns subscribed files; local inventory and modlist tools still work independently.
- Failures are truthful, partial results survive where possible, and native resources are cleaned up.
- Changes land as discrete, working commits with relevant tests and clear notes on unrun live checks.

## Reference

[Valve ISteamUGC documentation](https://partner.steamgames.com/doc/api/ISteamUGC) covers the target
query, subscription and item-state interfaces. Treat the installed DLL's ABI and observed behavior
as implementation gates; do not assume the latest documentation exactly matches that DLL.
