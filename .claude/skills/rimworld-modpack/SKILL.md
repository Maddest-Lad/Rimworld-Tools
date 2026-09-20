---
name: rimworld-modpack
description: Build, curate and maintain RimWorld modpacks (1.6, Windows/Steam) with the rimworld-tools MCP server - search and vet Workshop mods, resolve dependencies and DLC requirements, subscribe safely, sort load order into a cycle-free four-tier order, snapshot/diff for rollback. Use when the user wants a themed or curated modlist, wants to add or remove mods, has load-order, dependency or incompatibility problems, or wants their current mod setup reviewed.
---

# RimWorld modpack workflow

Every step is a `rimworld-tools` MCP call (`mcp__rimworld-tools__<name>`). They talk to the
signed-in Steam client; there is no web fallback. Read `reference/tool-outputs.md` for the exact
response fields, `reference/checklist.md` before adding any mod, `reference/frameworks.md` for
tiers and prerequisites, `reference/about-xml.md` for the About.xml / ModsConfig.xml fields.

## Ground rules

- **Read-only tools are free; call them liberally.** `workshop_subscribe`, `workshop_unsubscribe`
  and `sort_modlist(dry_run=False)` change the user's real account or list — state the exact
  pfids/effect and get a yes first.
- **Subscribed ≠ downloaded ≠ active.** `workshop_subscribe` success means subscribed; Steam
  downloads later (`check_mod_updates`); the user activates mods in-game. Nothing here writes
  `activeMods` except the sorter, which only reorders what is already active.
- **`sort_modlist()` returns the full order (288 entries on a big list).** Never echo it. Report
  `tiers`, `changed_positions`, `unresolved`, `duplicate_active`, `incompatible_active_pairs`,
  `dependency_issues`, and only the moves the user asked about.
- **A native lookup failure is a per-item `failed[].reason`, not proof of unpublishing.** Say what
  the reason was.
- Never hand-edit `ModsConfig.xml`, `links/workshop` or `links/steam`.

## 1. Baseline (every session)

```
environment_status()                       → ready, account, rimworld.version
modlist_snapshot(note="before <task>")     → id like 20260920T002230Z; remember it
list_installed_mods()                      → count, by_source, mods[], mods_with_advisories
diagnose_cycles()                          → cycles, incompatible_active_pairs, dependency_issues
```

If `ready` is false, stop and relay the reason. `diagnose_cycles` is the fastest health check:
each `dependency_issues[]` entry names the mod, the missing `package_id`, a `status`
(`not_installed` | `installed_but_inactive`) and a ready `action` (`workshop_subscribe` with `pfids`). Present
those before doing anything else — they are the problems the user already has.

Worked example from a real list: `Hospitality: Spa` requires `dubwise.dubsbadhygiene` but the
user has `dubwise.dubsbadhygiene.lite` active. The fix is a choice (swap Lite for the full mod,
or drop Spa), not a blind subscribe — ask.

## 2. Discover

| Input | Call | Read |
|---|---|---|
| URL or id | `resolve_workshop_url(url)` | `kind`: mod / collection / other / other_game / unknown; `title` |
| Collection | `collection_expand(url_or_id)` | `pfids[]` + `items[] {pfid, title}`; nested collections are dropped |
| Theme / name | `workshop_search(query, limit)` | `results[]`, `filters` (Mod + installed version tag, no Translation/Scenario) |
| Popular / new | `workshop_search(sort="trend", days=30)` / `"top"` / `"recent"` / `"updated"` | `sort="relevance"` needs a query |
| Older-version mods | `workshop_search(query, game_version="any")` | only when the user accepts the risk |

`total` (e.g. 1104 for "dubs bad hygiene") is a ranking pool, not a match count. Search is
capped at 100; page with `limit`. Results are cached 1h — `refresh=True` if the user just
published or updated something.

## 3. Vet

`workshop_mod_info(pfids)` in chunks of ≤50 (`include_description=True` only when you need the
text; it's 8 KB max, `description_may_be_truncated` flags the limit). Per item read:

- `tags` — must contain the installed `major.minor` (e.g. `"1.6"`). A mod tagged only `"1.5"`
  (real case: Titan Vehicles Upgrades, 3484382302) is exactly what later produces
  `XML error … doesn't correspond to any field` at startup.
- `time_updated` (epoch) vs `time_created` — stale for years + a `replaced` advisory = abandoned.
- `advisories[]` — `{kind, severity, message, action?}` with kinds `replaced`, `blacklisted`,
  `unpublished`, `version_mismatch`, `missing_dependency`. `action` is directly executable.
- `failed[]` — per-pfid `reason`; report, don't guess.
- `cache.note` — say when data came from cache if freshness matters.

Then the checklist in `reference/checklist.md` (frameworks first, DLC ownership via
`list_installed_mods(source="ludeon")`, `incompatible_with` vs the active list, duplicate
packageIds).

## 4. Subscribe and wait

1. Confirm the pfid list with the user, then `workshop_subscribe(pfids)` (≤50). Read
   `succeeded`, `failed[] {pfid, reason}`, `already_satisfied`.
2. Poll `check_mod_updates(pfids)` until each item has `installed: true`, `downloading: false`,
   `download_pending: false`. `not_installed[]` / `not_subscribed[]` / `outdated[]` are the
   shortcuts. Steam can take minutes for large mods (`bytes_downloaded` / `bytes_total`).
3. `list_installed_mods(package_ids=[...], detail=True)` — confirm `version_ok`,
   `supported_versions`, `dependencies[] {package_id, name, pfid}`, `load_after`, `load_before`,
   `incompatible_with` parsed. `include_invalid=True` shows folders whose About.xml failed.
4. Tell the user to enable the new mods in the in-game Mods menu, then continue to step 5.

## 5. Sort

1. `diagnose_cycles()` again. For a cycle, each edge carries `sources` (`about:<pid>`,
   `community`, `user`); the fix for a wrong community rule is a `removeLoadAfter` /
   `removeLoadBefore` entry in `rimworld-mcp/bin/dbs/userRules.json` (see `reference/about-xml.md`),
   never deleting a mod to break the loop.
2. `sort_modlist()` (dry run). Summarise: `tiers` counts, `changed_positions`, `unresolved` (ids
   active in ModsConfig but not on disk — usually a `_steam` entry whose Workshop copy is missing,
   or an unsubscribed mod; they stay at the end, never dropped), `duplicate_active`.
3. With the user's go-ahead: `sort_modlist(dry_run=False)`. It snapshots first, refuses while
   RimWorld is running, returns `snapshot_before`, and writes nothing if `ok` is false.
4. `modlist_diff(old="<baseline id>", new="current")` → `added`, `removed`, `moved` — that is the
   change report.

## 6. Maintain

- `check_mod_updates()` (no args = all subscriptions): `outdated[]` = installed copies Steam
  says need updating; Steam applies them itself, usually on next launch.
- After any subscribe/unsubscribe: `diagnose_cycles()` + dry-run sort.
- `modlist_snapshot(list_only=True)` → `snapshots[] {id, created_at, note, count}` for rollback
  points; `modlist_diff("<id>", "current")` to see what drifted.
- `workshop_unsubscribe(pfids)`: Steam deletes the Workshop folder after the game exits; copies
  in `links/mods` are untouched. A mod that is *also* in `links/mods` keeps working locally.
- Startup errors after a change → `/rimworld-log-debug` (its parser attributes XML errors to
  the mod by `[Source:]`; cross-check with `workshop_mod_info` tags).
