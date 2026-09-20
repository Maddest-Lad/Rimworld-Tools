# rimworld-tools response shapes

Captured from live calls against RimWorld 1.6.4871. Field names are exact; lists are `[]` when
empty. Expected failures come back as `{"error": ..., "hint": ...}` instead of raising.

## `environment_status()`

```json
{"ready": true, "account": "7656119…", "rimworld": {
  "game_dir": {"path": "…\\common\\RimWorld", "provenance": "Steam libraryfolders.vdf (AppID 294100)"},
  "mods_dir": {…}, "config_dir": {…}, "workshop_dir": {…}, "steam_root": {…},
  "version": "1.6.4871 rev590"}}
```

## `list_installed_mods(source?, package_ids?, detail=False, include_invalid=False)`

```json
{"game_version": "1.6.4871 rev590", "roots": {"data": …, "mods": …, "workshop": …},
 "count": 2, "by_source": {"steam": 2}, "mods_with_advisories": 0,
 "mods": [{"package_id": "brrainz.harmony", "name": "Harmony", "source": "steam",
           "pfid": "2009463077", "version_ok": true,
           "advisories": [{"kind": "replaced", "severity": "warning", "message": "…", "action": {…}}]}]}
```

`detail=True` adds per mod: `path`, `authors[]`, `supported_versions[]`, `mod_version`,
`dependencies[] {package_id, name, pfid}`, `load_after[]`, `load_before[]`, `incompatible_with[]`.
`source` ∈ `ludeon | steam | git | local`; `pfid` is null for `ludeon`; `version_ok` is null for
Core. A top-level `notice` appears once if a community DB is missing. `duplicates` lists
packageIds present in more than one source.

## `workshop_mod_info(pfids, refresh=False, include_description=False)`

```json
{"items": [{"pfid": "3484382302", "title": "Titan Vehicles Upgrades", "file_type": 0,
            "consumer_app_id": 294100, "creator": "7656119…", "time_created": 1747676560,
            "time_updated": 1748365069, "file_size": 880340, "tags": ["Mod", "1.5"],
            "tags_truncated": false, "visibility": 0, "url": "https://steamcommunity.com/…",
            "unpublished": false, "advisories": [...]}],
 "failed": [{"pfid": "…", "reason": "…"}],
 "cache": {"hits": ["…"], "fetched_live": ["…"], "oldest_cached_at": "…", "note": "1 of 2 from cache …"}}
```

With `include_description=True`: `description` and `description_may_be_truncated`. Version
compatibility = `tags` contains the installed `major.minor`. `visibility` 0 = public.

## `workshop_search(query="", limit=20, game_version=None, include_translations=False, include_scenarios=False, sort="relevance", days=90, refresh=False)`

```json
{"results": [<same item shape as workshop_mod_info>], "total": 1104, "failed": [],
 "filters": {"required_tags": ["Mod", "1.6"], "excluded_tags": ["Translation", "Scenario"], "sort": "relevance"},
 "query": "dubs bad hygiene"}
```

`total` is Steam's ranking pool, not a textual match count. Hard cap 100 results.

## `resolve_workshop_url(url)` / `collection_expand(collection_url_or_id)`

```json
{"pfid": "836308268", "kind": "mod", "title": "Dubs Bad Hygiene", "cache": {…}}
```

`kind` ∈ `mod | collection | other | other_game | unknown`. `collection_expand` returns
`{collection, count, pfids[], items[] {pfid, title}, failed[], hint, cache}` — mods only, nested
collections dropped; feed `pfids` straight into `workshop_mod_info` / `workshop_subscribe`.

## `check_mod_updates(pfids=None)`

```json
{"items": [{"pfid": "2009463077", "subscribed": true, "installed": true, "needs_update": false,
            "downloading": false, "download_pending": false, "source": "steam", "path": "…",
            "installed_at": 1756914561, "size_on_disk": 5729526, "bytes_downloaded": 0, "bytes_total": 0}],
 "outdated": [], "not_installed": [], "not_subscribed": [], "failed": [],
 "hint": "Live Steam client state; … installed_at is the installation timestamp …"}
```

"Ready to use" = `installed && !downloading && !download_pending`. Always live, never cached.

## `workshop_subscribe(pfids)` / `workshop_unsubscribe(pfids)`

```json
{"succeeded": ["…"], "already_satisfied": ["…"], "failed": [{"pfid": "…", "reason": "…"}]}
```

Validates that items belong to RimWorld before dispatching. Success = subscription state
changed, not downloaded.

## `diagnose_cycles()`

```json
{"ok": true, "failed_tier": null, "cycles": [], "incompatible_active_pairs": [],
 "dependency_issues": [{"mod": "Hospitality: Spa", "requires": "Dubs Bad Hygiene",
                        "package_id": "dubwise.dubsbadhygiene", "status": "not_installed",
                        "action": {"tool": "workshop_subscribe", "pfids": ["836308268"]}}],
 "hint": null}
```

A cycle entry lists its edges as `after -> before` with `sources` (`about:<pid>`, `community`,
`user`). `status` ∈ `not_installed | installed_but_inactive`.

## `sort_modlist(dry_run=True)`

```json
{"dry_run": true, "active_count": 288, "ok": true, "changed_positions": 127,
 "unresolved": ["sarg.alphaanimals"], "duplicate_active": [], "incompatible_active_pairs": [],
 "dependency_issues": [...], "user_rule_removals_applied": [],
 "order": [{"package_id": "zetrith.prepatcher", "name": "Prepatcher"}, …],
 "tiers": {"tier0": 10, "tier1": 7, "tier2": 266, "tier3": 3},
 "hint": "Unresolved ids (not installed) are kept at the end of the list, not dropped."}
```

`order` is the full list — summarise, never paste. On a cycle `ok` is false, `failed_tier` is
set, and a write does nothing. A write additionally returns `snapshot_before` (the id it saved first).

## `modlist_snapshot(note="", list_only=False)` / `modlist_diff(old="latest", new="current")`

```json
{"snapshots": [{"id": "20260920T002230Z", "created_at": "2026-09-20T00:22:30+00:00", "note": "…", "count": 288}]}
```

`modlist_diff` refs: `current` (ModsConfig.xml), `latest` (newest snapshot) or an `id`. Returns
`added[]`, `removed[]`, `moved[]`.
