---
name: rimworld-modpack
description: Build, curate and maintain RimWorld modpacks (1.6, Windows/Steam) with the rimworld-tools MCP server - search and vet Workshop mods, resolve dependencies and DLC requirements, subscribe safely, sort load order into a cycle-free four-tier order, snapshot/diff for rollback. Use when the user wants a themed or curated modlist, wants to add or remove mods, has load-order, dependency or incompatibility problems, or wants their current mod setup reviewed.
---

# RimWorld modpack workflow

Every step below is a `rimworld-tools` MCP tool call. The tools talk to the signed-in Steam
client; there is no web fallback. Folders are reachable through `links/` (see the workspace
`CLAUDE.md`). Read `reference/frameworks.md` for tier rules and framework prerequisites,
`reference/checklist.md` before adding any mod, and `reference/about-xml.md` for the
About.xml / ModsConfig.xml fields that matter.

## 1. Establish the baseline (always)

1. `environment_status()` — stop and report if the game is not found or Steam is offline.
2. `modlist_snapshot(note="before <what you are about to do>")` — makes the whole session
   reversible with `modlist_diff`.
3. `list_installed_mods()` — what is on disk (`source`: ludeon | steam | git | local, `version_ok`,
   advisories). Add `detail=True` only for the mods you are investigating; the compact form is
   enough for an overview.
4. `check_mod_updates()` — pending downloads and outdated Steam copies. Resolve these before
   adding more mods; a half-downloaded mod parses as broken.

## 2. Discover candidates

| User gives | Call |
|---|---|
| A Workshop URL or id | `resolve_workshop_url(url)` → `kind` is `mod` or `collection` |
| A collection | `collection_expand(url_or_id)` → member pfids (nested collections are filtered) |
| A theme / name | `workshop_search(query, sort="relevance")`; `sort="trend"` / `"top"` / `"recent"` / `"updated"` for browsing |
| "What changed recently for X" | `workshop_search(query, sort="updated")` |

Search defaults to the installed game version tag and excludes Translation/Scenario items.
`total` is a ranking estimate, not a match count; if the hit list looks off, say so.

## 3. Vet before subscribing

`workshop_mod_info(pfids, include_description=True)` in chunks of ≤50. For each candidate run
`reference/checklist.md` — the short version:

- Version tag / `version_ok` (the No Version Warning DB already suppresses known false positives;
  do not second-guess a mod it lists).
- Advisories: `replaced` → use the fork instead; `blacklisted` → tell the user why and skip;
  `missing_dependency` → the advisory carries a ready `workshop_subscribe` action.
- Framework prerequisites (Harmony, HugsLib, Vanilla Expanded Framework, XML Extensions …) —
  queue those *first*.
- DLC requirements (`ludeon.rimworld.royalty|ideology|biotech|anomaly|odyssey`) against
  `list_installed_mods(source="ludeon")`.
- `incompatibleWith` and duplicate `packageId` against the current active list.
- A native lookup failure is a per-item reason, **not** proof the mod is unpublished.

## 4. Subscribe and wait

1. `workshop_subscribe(pfids)` (≤50 per call). Read `succeeded` / `failed[]` /
   `already_satisfied`. Success means *subscribed*, not downloaded.
2. Poll `check_mod_updates(pfids)` until every id is installed and nothing is pending. Do not
   inventory or sort before this — About.xml may not exist yet.
3. `list_installed_mods(package_ids=[...], detail=True)` for the new mods: confirm `version_ok`,
   dependencies and load rules parsed.

Subscribing does **not** activate a mod. Tell the user to enable it in the in-game mod menu (the
sorted list only covers what is already active). Never hand-edit `ModsConfig.xml`.

## 5. Sort

1. `diagnose_cycles()` — cycles (each edge with its rule source `about:<pid>` / `community` /
   `user`), incompatible active pairs, missing or inactive dependencies. Fix the cause: subscribe
   the missing dependency, ask the user which of an incompatible pair to drop, or add a
   `removeLoadAfter` / `removeLoadBefore` entry to `rimworld-mcp/bin/dbs/userRules.json` for a
   wrong community rule.
2. `sort_modlist()` (dry run) — review tier 0/1 contents and anything that moved a long way.
3. `sort_modlist(dry_run=False)` only after the user agrees. It snapshots first, refuses while
   RimWorld is running, and writes nothing if a cycle remains.
4. `modlist_diff(old="<snapshot id from step 1>", new="current")` — report added / removed /
   moved in plain language.

## 6. Maintenance

- `check_mod_updates()` on request; `outdated` lists installed Steam copies awaiting updates.
- After any subscribe / unsubscribe, rerun `diagnose_cycles()` and a dry-run sort.
- `modlist_snapshot(list_only=True)` to offer rollback points; `modlist_diff` between two ids.
- `workshop_unsubscribe(pfids)` removes the subscription; Steam deletes files after the game
  exits and local copies in `links/mods` are untouched.

## Hard rules

- Mutations (`workshop_subscribe`, `workshop_unsubscribe`, `sort_modlist(dry_run=False)`) touch
  the user's real account and list — confirm the exact ids first.
- Local (`links/mods`) and Steam copies of the same `packageId` coexist; RimWorld's `_steam`
  suffix in `ModsConfig.xml` marks which one is active. Respect it and never delete either copy.
- Do not walk `links/workshop` or `links/mods` wholesale — `list_installed_mods` already parsed
  them. Open a single mod folder only to inspect a specific About.xml or patch.
- Errors at game start after a change → switch to `/rimworld-log-debug`.
