# Architecture review and refactoring plan

Historical review: the Steam Web API and SteamCMD backend direction below is superseded by
[the Steam Client API consolidation plan](STEAM_CLIENT_MIGRATION.md).

Review date: 2026-09-19. Status: proposal; implementation has not started.

Scope: the current MCP server, tests, configuration, and project documentation. Windows 10 LTSC is the only required operating environment. Future skills, game-log tooling, and Steam account subscription management are design considerations, not implementation work in this refactor.

## Assessment

Keep the current functional core. Thin MCP declarations, explicit dataclasses, the pure sorting algorithm, per-edge provenance, tolerant About.xml parsing, and partial Workshop results are good foundations. A framework rewrite or generic plugin architecture would add complexity without solving the current problems.

The missing piece is ownership of runtime state and prerequisites. Each tool constructs settings and independently discovers paths, loads databases, or creates caches. Setup is a conversation the model must orchestrate, and mutable resources have no shared coordination. Introduce one small runtime coordinator, then consolidate duplicated responsibilities around it.

There are correctness fixes to make before automatic setup: downloads do not validate their destination junction; sorting can compile rules from a different copy than the selected mod; deletion does not establish management ownership; and several file operations are vulnerable to concurrent calls or interrupted writes.

## Evidence and validation

- Read all 15 Python modules and reviewed test coverage and representative fixtures across the 13 test files, plus repository documentation and relevant clean-room research notes.
- Existing suite: **149 passed**. Ruff passed; Black reported all 28 source/test files unchanged.
- Test bootstrap replaced `dotenv.load_dotenv` with a no-op before importing project code. No secret file was read. Initial fixture creation was blocked by sandbox permissions on Windows Temp; the approved rerun passed.
- No live SteamCMD install/download/delete, database synchronization, game configuration edits, or Steam account changes were performed. Findings below are source-level findings; the existing passing suite does not exercise all of them.
- RimSort source was not read or copied. Local research notes were used only to clarify intended sorting semantics.
- Installed FastMCP is 4.0.5, while the declared dependency is `fastmcp>=2.0.0`. Lifecycle integration should target a deliberately supported version range.
- `docs/` is entirely ignored. This review is at the repository root so it can be versioned without changing the treatment of local research.

## Proposed environment lifecycle

Use internal `ensure_environment(requirements)` orchestration. Do not replace several setup tools with another setup tool the assistant must remember to call.

Recommended flow:

1. At server startup, explicitly load and validate settings and construct the runtime. Cheap local discovery may run here; neither missing RimWorld nor a network outage should prevent tool discovery and remote Workshop queries.
2. At operation entry, request only the capabilities that operation needs. Cache successful discovery and database loads, but revalidate mutation-critical paths while holding the relevant lock.
3. Install and warm SteamCMD lazily before the first download. Confirm its content junction targets the selected Mods directory before launching it. Existence of `steamcmd.exe` alone is not readiness.
4. Obtain required community data lazily; subsequently use a freshness policy and conditional requests. Retain the last validated data when offline. Missing advisory data degrades with one concise notice. Missing sorting rules need an explicit policy before writes.
5. After a download, deletion, database replacement, or configuration change, invalidate only affected cached state. External game/Steam/file edits also require freshness checks; a lifetime boolean is insufficient.
6. On shutdown or cancellation, stop and reap owned subprocesses, finish cleanup, then release locks. Never kill an unrelated Steam client or externally launched SteamCMD.

Suggested responsibilities are intentionally small: `Runtime` owns settings, discovered paths, shared cache/database readers and operation coordination; `Environment` establishes capabilities. Domain functions receive the state they need rather than performing discovery themselves. Avoid a service locator passed into every parser.

| Operation | Required state | Automatic preparation |
|---|---|---|
| Remote info, URL resolution, collection expansion | Web API/cache; optional advisory DBs | No game install or SteamCMD required |
| Workshop search | Web API/cache; optional detected version | Missing API key retains browse-URL fallback; unknown game version must be explicit |
| Installed-mod inventory | Discovered roots; advisory DBs optional | Read paths, scan metadata, refresh relevant optional data |
| Update check | Correct Steam library and SteamCMD manifests | Read manifests; never install SteamCMD just to inspect updates |
| Download/update | Writable selected Mods root, ready SteamCMD, verified junction | Lazy install/warm-up and safe link creation under mutation lock |
| Delete | Established managed storage and item ownership | Validate existing state; do not download/install anything to delete |
| Sort/diagnose | Config, inventory, selected-copy metadata, rules | One consistent read context; writes additionally snapshot and check file revision |
| Snapshot/diff | Config and/or snapshot store | No SteamCMD or remote database prerequisites |
| Environment status | Available local state | Inspection only; no installation or synchronization |

Automatic setup may create absent directories and owned links. It must not force-replace a non-empty directory, repoint an unowned link, delete mods, or silently rewrite an active list. Such obstructions produce a concrete repair description for an explicit maintenance action.

Use one installation operation for concurrent first calls. Support two MCP processes sharing the same prefix: an `asyncio.Lock` alone is insufficient. A per-prefix OS/file lock coordinates setup, downloads, depot clearing, deletion, and ACF repair for the entire mutation. A separate config lock protects list writes. External SteamCMD detection remains a guard, not the locking mechanism. Define lock ordering and bounded waiting; return a useful busy result instead of hanging indefinitely.

## Default MCP surface

There are currently 19 tools. A first migration can reduce this to 13 without obscuring normal user actions behind a generic dispatch tool.

| Current tools | Proposed treatment |
|---|---|
| `rimworld_locate`, `steamcmd_status` | Replace with one read-only `environment_status`; compact readiness by default, detailed paths/provenance when requested |
| `steamcmd_setup` | Internal lazy preparation; explicit reinstall/repoint available through maintenance CLI |
| `db_sync` | Internal freshness policy; manual refresh through maintenance CLI |
| `clear_depot_cache`, `acf_repair`, `cache_clear` | Maintenance CLI; retain targeted download remediation where appropriate |
| `list_installed_mods`, `workshop_search`, `workshop_mod_info`, `check_mod_updates` | Retain as separate user operations |
| `collection_expand`, `resolve_workshop_url` | Retain initially; accept URLs at operation boundaries later if it materially reduces calls |
| `workshop_download`, `workshop_delete` | Retain; describe explicitly as local install/update/remove |
| `sort_modlist`, `diagnose_cycles` | Share one analysis pipeline; consider renaming diagnostics to `diagnose_modlist`, since it already includes dependency and incompatibility checks |
| `modlist_snapshot`, `modlist_diff` | Retain initially; move snapshot-list branching out of the server body |

An opt-in maintenance MCP profile is possible if CLI recovery is too awkward, but those tools should not be advertised by default. Do not rely on clients hiding deprecated tools: registration itself must select the surface. Remove obsolete setup instructions and action references from all results and docstrings at the same time.

Model-facing payload size also matters. Add bounded/paginated inventory, update, collection, and snapshot results as needed, with explicit totals and truncation/cursors. Return a compact cache summary by default; hundreds of cache-hit IDs duplicate the main result. Keep detailed diagnostics available on request. Measure serialized tool descriptions and representative 300-mod responses before and after.

## Prioritized work items

P1 means correctness or data integrity that should precede automatic mutation. P2 means architecture, reliability, or contract work for this refactor. P3 means optional simplification after behavior is stable.

### A01 — P1: coordinate SteamCMD lifecycle and verify output

Evidence: `steamcmd.py:179` (`run_batch`), `:225` (`warm_up`), `:267` (`download`), `:375` (`setup`). Download checks only executable existence. Runs share one console log and ACF without a common lock. Setup and depot clearing can overlap them. Cancellation does not kill/reap the subprocess; subprocess launch occurs before the cleanup block. Warm-up treats any process exit as success. Installation can leave an executable behind after incomplete setup, and a later call skips warm-up.

Plan: add the shared mutation lock and explicit readiness states; separate installer, process runner and orchestration only along those responsibilities. Wrap launch and execution in guaranteed cleanup, make warm-up failures prevent readiness, and keep retry possible. Move blocking setup/cache filesystem work off the event loop. Track requested IDs in the parser so unrelated log lines cannot become batch successes; keep a bounded tail rather than the first 200 lines followed by their last 40. After a reported success, verify the expected mod directory/content exists and report suspect success rather than silently trusting it. Preserve the 25-item limit, anonymous login, log tailing, and pending-set accounting.

Acceptance: concurrent first downloads perform one install; competing mutations serialize across processes; wrong junction prevents launch; launch failure/cancellation/timeouts clean up; warm-up failure is retryable; success-without-files is reported. Depot reset or ACF repair must never be an unconditional pre-call side effect.

### A02 — P1: make local removal ownership-aware and recoverable

Evidence: `workshop.py:282` deletes `mods_dir / pfid` whenever it is a real directory, whether or not the SteamCMD ACF records that item. A numeric folder is not proof of management ownership. A skipped junction still produces a `deleted` entry; manifest removal and final ACF save can fail after other items have already been removed.

Plan: represent a managed item explicitly, using manifest provenance and the verified storage layout, not the inventory's heuristic source label. For orphan recovery, require an explicit policy/action rather than silently taking ownership. Validate the target root and item immediately before mutation. Preserve the existing refusal to recurse into an item link. Report skipped/blocked items honestly and capture each filesystem failure. Use staging/quarantine or an operation record to make partial directory/manifest/ACF changes recoverable; do not claim they are one atomic transaction.

Acceptance: an unmanaged numeric folder survives deletion; junction targets survive; ACF/manifest errors produce accurate partial results and a repair path. Steam client content is never removed as a side effect of local SteamCMD removal.

### A03 — P1: use selected-copy metadata consistently

Evidence: `modlist.py:194` (`prepare`) builds `abouts` from the first inventory copy before `_choose` selects the actual active copy. With `author.dup_steam`, names and dependency checks can use the Workshop copy while sorting/incompatibility rules use the local copy.

Plan: resolve active config entries first, then derive their metadata and rule graph from those resolved copies. Share that same resolved view across sorting, dependency diagnostics, incompatibilities and serialization. Normalize config IDs and suffix handling in one helper; detect duplicate active entries rather than silently collapsing them through dictionaries. Add a package-ID secondary sort key when display names compare equal so set iteration cannot change the result.

Acceptance: local and Workshop copies with deliberately conflicting rules use the selected copy; mixed casing and `_steam` round-trip; duplicate config entries have an explicit diagnostic/policy; equal display names sort consistently across processes.

### A04 — P1: protect ModsConfig and snapshot persistence

Evidence: `modlist.py:44` overwrites XML in place; `:79` uses second-resolution snapshot IDs; `:118` joins a user-supplied snapshot reference directly into a path. Sorting reads config, then snapshots by discovering and reading it again, then overwrites the original path without detecting external edits. XML is reconstructed from three known fields.

Plan: validate snapshot identifiers and confine references to the snapshot store. Use collision-resistant IDs and exclusive creation. Snapshot the exact bytes/revision being replaced, retain unknown XML fields, and write a same-directory temporary file followed by replacement. Compare the current revision immediately before commit; return a conflict if RimWorld or another manager changed it. Backups do not replace that check. Snapshot failure must stop the write. Document the remaining race with uncooperative external writers and choose whether to refuse edits while the game is running.

Acceptance: two snapshots in one second both survive; traversal/absolute refs are rejected; malformed XML becomes an expected error; failed writes leave the prior config intact; external changes are not silently overwritten; unknown fields and unresolved entries survive.

### A05 — P1: fix cache ownership and lost updates

Evidence: `workshop.py:36` constructs a new `Cache` per call. `cache.py:84` gives each instance its own lock and loaded dictionary, while `:103` uses the same `.json.tmp` name. Two instances can lose each other's updates even sequentially after both have loaded the old file; concurrent writes also contend for one temporary path. A separately constructed clear operation cannot invalidate other instances' memory.

Plan: runtime-owned cache within a process plus cross-process coordination. The minimal implementation is a lock around reload/merge/write, a unique temporary file and revision-aware reads; retain JSON initially. Consider SQLite only if measured contention or size warrants it. Validate loaded cache shapes, make corrupt entries misses, bound/prune expired entries, and prevent cache-write failure from discarding successful live API results.

Acceptance: interleaved instances preserve both updates; clear is visible to existing readers; two processes cannot collide on temporary files; malformed cache or read-only cache storage degrades to live results with a concise notice.

### A06 — P2: centralize discovery and preserve library/source provenance

Evidence: `workshop.py:16` and `mods.py:391` locate the Steam client ACF beneath the Steam installation root, although `paths.py` can discover RimWorld in a secondary library. Timestamp maps also merge SteamCMD and Steam-client copies by PFID, losing source identity. Several functions rediscover paths during one operation; library manifest parsing repeats. Explicit Mods overrides are reported as found without validation. Windows-only imports are expected for the agreed scope.

Plan: return the selected Steam library and its Workshop ACF as part of discovery; carry `(source, pfid)` identity for installed records and timestamps. Read discovery once per operation context, cache carefully between calls, and distinguish configured, existing and writable paths. Add game/config overrides only where needed for this machine and first-run recovery. Handle case and canonical path identity consistently. Keep Windows registry/LocalLow/junction logic in concrete Windows modules with small callable boundaries, without implementing other platforms.

Acceptance: secondary-library updates use the correct ACF; duplicate copies keep separate timestamps; changed/missing roots refresh correctly; remote queries remain usable without a game install.

### A07 — P2: fix community-reader caching and version scope

Evidence: `db.py:183` clears the entire reader cache whenever another file is loaded, so `Context.load` can repeatedly parse the large Steam DB. The global dictionary has no synchronization. `db.py:360` falls back to an arbitrary version's No Version Warning file when the requested version is absent, contrary to the documented version-scoped policy. Corrupt optional data propagates parse errors. `check_updates`, sort and diagnose do not consistently report missing community data.

Plan: cache per canonical file and revision (at least nanosecond mtime plus size, or published generation), evict only the replaced entry, and coordinate loads. Select only the exact game's version directory for warning suppression; unknown/missing version means unavailable data. Separate optional-data failures from invalid user rules: bad community data should degrade with provenance; bad user rules must block a write rather than silently discard user intent. Centralize one top-level data-quality notice. Make raw declared version support distinguishable from the resolved advisory result.

Acceptance: repeated multi-DB loads parse unchanged files once; concurrent readers are safe; missing 1.6 data never applies 1.5 suppression; malformed optional DBs do not abort inventory; bad user rules are actionable.

### A08 — P2: make database refresh transactional and bounded

Evidence: `db.py:71` uses fixed `.new`/`.bak` directories, removes previous staging/backup content, and has no rollback if the final rename fails. `sync_one` replaces the current database before validating its expected file/schema. Saved fallback-branch metadata is not used to select the next request, and a 304 can leave a missing local dataset missing.

Plan: lock per source, extract into unique staging, validate the expected format (including versioned No Version Warning layout), then publish with rollback. Preserve the last known good dataset. Record successful checks separately from content updates; reuse branch and ETag together. Only use conditional fetch if valid local content exists. Add reasonable download/extraction limits and shared safe archive handling with the SteamCMD installer, while preserving their distinct deployment semantics.

Acceptance: failed extraction, invalid schema and rename failure preserve previous data; simultaneous refreshes do not delete each other's staging; branch fallback remains conditional on subsequent calls; absent local content is recovered despite old metadata.

### A09 — P2: unify identifiers and expected-failure contracts

Evidence: `workshop.py` imports private `steamcmd._normalise_pfids`; URL parsing differs between `mods.py` and `webapi.py`; numeric validation admits zero, leading-zero aliases and non-ASCII digit forms. Error shapes vary between bare error strings, missing hints, ID lists and per-item reason lists. Expected filesystem/XML/VDF failures still escape several operation boundaries. Unknown timestamps become `outdated=False` in `workshop.py:101`.

Plan: introduce a small shared identity module for canonical positive ASCII PFIDs, Workshop URLs, package IDs, game versions and config references. Keep tolerant file parsing separate from strict user-input validation. Use typed internal results and a consistent model-facing error vocabulary (`code`, `error`, `hint`, optional retryability) with explicit per-item failure reasons. Catch known operational exceptions at service boundaries without hiding programming errors. Preserve unknown freshness as null/unknown and report invalid requested update IDs rather than dropping them.

Acceptance: identifier forms agree across tools; invalid inputs do not reach subprocesses/filesystem mutations; missing permissions, corrupt manifests and malformed config produce useful results; batch progress is retained; missing timestamps never claim an item is current.

### A10 — P2: clarify remote metadata semantics and HTTP behavior

Evidence: `webapi.py:91` marks every `result != 1` as unpublished, including missing/other failure codes, and caches the normalized record. `resolve_url` labels any successful non-collection lookup a mod without checking its returned consumer app. Search GETs bypass the POST retry policy; private/deleted page probing does not inspect HTTP status. Sessions are recreated for individual requests/attempts.

Plan: retain remote status codes and distinguish successful metadata, unavailable/private/deleted evidence, and transient/unknown failure. Cache only appropriate states and keep timestamps visible. Validate RimWorld identity before calling an item a RimWorld mod; preserve unknown type where the endpoint cannot establish it. Centralize timeouts, bounded retry/backoff and key redaction, honoring Retry-After when applicable. Keep synchronous HTTP in worker threads for now; do not add an async HTTP migration merely for style. Use scoped sessions with explicit thread ownership if pooling is introduced.

Acceptance: transient item failures do not become removal advisories; foreign-game items are rejected or classified accurately; 403/429/5xx and malformed responses have consistent results; sentinel probing on an HTTP error cannot confirm availability; secrets remain absent from errors/logs.

### A11 — P2: consolidate analysis and make read operations predictable

Evidence: dependency naming/remediation logic overlaps `advisories.missing_dependency` and `modlist.prepare`; `sort_modlist` and `diagnose` shape overlapping results independently. `prepare` returns either a dataclass or a dict. Reading user rules seeds a file; listing snapshots creates a directory. `sorting.py` depends on `db.Rule`, tying a pure algorithm's input type to storage.

Plan: extract shared dependency evaluation and one typed `ModlistAnalysis`. Keep analysis, sorting, advisory formatting and config commit distinct. Move small domain records to a shared module only when this removes real dependencies; do not introduce repositories/interfaces for every function. Reading absent rules returns an empty/default view; environment preparation or a write creates files deliberately. Make snapshots a small persistence component if that simplifies `modlist.py`.

Acceptance: sort and diagnose agree on selected copies/issues; read-only operations do not seed user files unexpectedly; domain tests construct rules without database I/O; MCP remains a thin adapter.

### A12 — P2: explicit configuration and reproducible tests

Evidence: `config.py:22` loads dotenv at import time; the dataclass's default repr includes the API key. Settings are rebuilt per tool while dotenv is loaded only once, creating unclear reload semantics. Negative download caps are accepted and malformed values silently default. Server tests only list tools/check descriptions. Current batch tests replace `run_batch`, so they do not exercise subprocess cleanup.

Plan: explicit startup configuration loading, redacted secret fields, validated positive bounds and absolute paths, and documented restart/reload behavior. Permit settings injection into server construction for tests. Add shared fixtures isolating environment, discovery, network, game paths and storage. Add representative MCP client calls through the actual adapter, not just direct service tests. Test locks, cancellation, first-use preparation, offline operation and fault injection. Continue Windows-specific junction tests; no other OS implementation or CI matrix is needed.

Acceptance: importing pure modules never loads local configuration; fixtures cannot touch real game state or credentials; invalid config is reported once; actual tool calls preserve contracts; tests cover the new failure modes rather than merely mirroring implementation.

### A13 — P2: define workspace aliases separately from SteamCMD plumbing

Evidence: `symlink.ensure_junction` currently supports only the SteamCMD output link used by setup. There is no managed set of game/config/log/Workshop aliases.

Plan: keep the required SteamCMD content junction distinct from optional workspace navigation aliases. If wanted, create a small owned `links/` layout for game, Mods, config/user-data/log parent and Workshop roots, with target provenance and a manifest. Ignore the alias tree in Git before creating links. Create only validated targets; report missing ones without blocking unrelated capabilities. Repoint only links proven owned by this tool, and never recursively remove their targets. Expose real target paths in diagnostics.

Aliases simplify navigation; they do not grant access or replace an assistant host's approval checks. Validate their behavior with the actual hosts separately. No platform abstraction beyond the existing Windows filesystem boundary is necessary.

Acceptance: second initialization is a no-op; obstruction is preserved; stale owned links can be repaired explicitly; missing log/config directories are tolerated; Git cannot traverse game data through the alias tree.

### A14 — P2: reconcile documentation and runtime packaging

Evidence: README still calls the server planned and describes RimSort integration for metadata/sorting, which contradicts current functionality and the reference-only rule. AGENTS includes a manual setup sequence that will become obsolete. `pyproject.toml` uses a broad FastMCP lower bound and `package=false`; startup depends on repository cwd and the `src.rimworld_tools` namespace. A SteamCMD binary is tracked despite runtime installation.

Plan: document the actual feature set, Windows 10 LTSC scope, local install/remove semantics, automatic preparation, offline behavior and recovery commands. Keep shared instructions assistant-neutral. Separate stable architecture/operations docs from ignored research. Choose a supported FastMCP range, keep the lockfile authoritative, and add lifecycle/schema smoke tests before updates. Provide native PowerShell/uv commands; Make can remain optional. Decide whether to retain repo-local launch now or add a small console entry point; defer distribution packaging if not needed. Decide whether the tracked bootstrap executable is intentionally part of first-run support.

Acceptance: a fresh checkout has one documented launch path and no model-orchestrated setup sequence; instructions contain no runtime RimSort dependency; tool references match registration; dependency resolution reproduces the tested version.

### A15 — P3: limited cleanup after behavior is stable

Remove truly unused helpers/constants, simplify `RimWorldPaths.to_dict` to the already recursive `asdict`, remove unused parameters such as `_timestamps(..., inv)` after consolidating manifest access, use keyword arguments for long service calls, and share response formatting only where semantics match. Consider using NetworkX for both topological generations and cycle reporting to remove `toposort`, but only with ordering regression fixtures proving level/tie behavior remains equivalent. Avoid file splitting solely to meet an arbitrary line count. Do not replace the tolerant XML parser, graph provenance or established SteamCMD handling as cosmetic cleanup.

## Decisions for the owner

| ID | Decision | Recommendation and consequence |
|---|---|---|
| D1 | Startup versus lazy setup | Cheap startup + capability-specific lazy preparation. First download can be slow; search and local read tools remain available without full setup. |
| D2 | Maintenance access and compatibility | Default 13-tool surface, maintenance CLI, optional legacy/maintenance registration if existing prompts need migration. No generic all-purpose MCP dispatcher. |
| D3 | Community refresh and incomplete sorting | Proposed 24-hour conditional refresh interval, one bounded missing-data attempt, last-good data offline. Read-only diagnosis can be degraded; block writing a sort with unavailable community rules unless explicitly overridden. This changes current permissive behavior. |
| D4 | Meaning of subscribe/unsubscribe | Keep this refactor to local install/remove. Real Steam account subscriptions are absent and would be a separate integration/authentication design. Clarify terminology now. |
| D5 | Workspace alias coverage | Add only the useful game/Mods/config-user-data/Workshop aliases under an ignored owned directory; defer log-specific behavior until the log feature exists. Decide whether all these aliases are useful on this machine. |
| D6 | Dependency-derived ordering | Preserve current explicit load-rule behavior initially. `modDependencies` currently feeds diagnostics, not ordering; the research describes inferred ordering as opt-in. If wanted, add a distinct policy with provenance and conflict tests, rather than silently changing sorting during refactoring. |
| D7 | Active-list editing while the game runs | Recommend refusing config writes while RimWorld is running, plus revision checks for other writers. Read-only analysis remains available. |
| D8 | Durability of local removals | Recommend temporary quarantine with bounded retention for managed removals. If disk use rules this out, document irreversible partial-operation recovery and retain an operation record. |
| D9 | Distribution scope | Keep repo-local uv launch for this personal Windows deployment unless installation outside the checkout is a near-term requirement. A small future entry point is sufficient; no packaging framework needed now. |

Windows 10 LTSC-only support is already decided. These recommendations can serve as defaults for discussion; no implementation decisions have been applied by this review.

## Delivery sequence

1. **Behavioral baseline and targeted fixes:** A03, A04, A06 and the version-scope portion of A07. Add regression cases that fail for the identified defects; preserve existing semantics except explicitly documented fixes.
2. **Safe shared state:** A01, A02, A05, A08 and configuration/test isolation from A12. Establish locks, recovery and cancellation before adding automatic mutation.
3. **Runtime and environment preparation:** implement the lifecycle proposal, shared discovery/DB readers and invalidation. Initially route existing tools through it so behavior changes can be tested independently of tool removal. Resolve D1, D3 and D7 here.
4. **MCP surface and contracts:** A09, A10, A11; default tool reduction, payload limits, annotations appropriate to actual side effects, and maintenance CLI. Resolve D2/D4 and update every hint/action that names a removed tool.
5. **Owned links and documentation:** A13/A14, governed by D5/D9. Include a manual first-run check on this Windows 10 LTSC installation; live install/download/removal checks are separate from unit tests and should use a deliberately chosen disposable mod/workspace.
6. **Measured simplification:** A15 and any further scan/HTTP optimization supported by timings. Leave future skill/log/subscription features out of these changes.

Each stage should be independently reviewable. Completion criteria include the existing suite and style checks, focused regression/failure-injection tests, two-process mutation/cache checks, MCP adapter calls, and a compact default tool-schema/response comparison. Do not remove maintenance capabilities before their automatic and explicit recovery replacements work.

## Deliberately deferred

Actual Steam account subscribe/unsubscribe, enabling/disabling mods or restoring a snapshot through new tools, game-log tailing/analysis, automatic dependency installation or replacement, general mod-authoring skills, remote distribution, Linux/macOS support, a generic job system, and a wholesale async-HTTP/storage rewrite. Snapshot restore and active-list editing are real product gaps relative to full modlist management; they should use the safe commit/analysis boundaries established here when implemented.
