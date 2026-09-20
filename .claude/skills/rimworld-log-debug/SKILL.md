---
name: rimworld-log-debug
description: Diagnose errors and crashes in RimWorld's Player.log (Windows/Steam 1.6, Unity/Mono). Use when the user pastes a RimWorld log or stack trace, reports red errors, a crash, a broken save, startup failures after changing mods, or asks which mod is causing a problem. Streams and dedupes huge logs with scripts/parse_log.py, classifies known signatures, attributes them to mods, and hands load-order and dependency issues to the rimworld-tools MCP tools.
---

# RimWorld log triage

`Player.log` grows to hundreds of MB. **Never `Read` or `cat` it.** Always start from the
parser, which streams the file once and reports only unique signatures with counts:

```sh
python .claude/skills/rimworld-log-debug/scripts/parse_log.py --since-startup --top 15
```

| Need | Flags |
|---|---|
| Previous run (game already restarted) | `--prev` |
| Machine-readable | `--json` |
| Only one mod's entries | `--mod <packageId, pfid, namespace or display-name fragment>` |
| Raw search inside entries | `--grep "<regex>"` |
| Better namespace → packageId attribution | save `list_installed_mods(detail=True)` output to a file and pass `--mods-json <file>` |
| Some other log (user pasted / HugsLib gist download) | positional `FILE` |

Logs live in `links/logs/` (`Player.log`, `Player-prev.log`, `HugsLib/`). RimWorld's in-game
debug log and HugsLib's Ctrl+F12 "share logs" upload contain the same entries.

## Triage flow

0. **Check `notes/accepted.md`** for signatures or mods already accepted; they go in the
   "noise" line of the report, not the findings.
1. **Run the parser.** Note the session count (one per game launch in the file), the active mod
   count RimWorld printed, the *first real error* and the top table.
2. **Fix the first load error first.** RimWorld merges all XML into one document; a single
   `XML error` / `Could not find a type` cascades into dozens of unrelated-looking
   `cross-reference` and `Def named X not found` entries. Do not chase anything below the first
   `load`-kind error until it is resolved.
3. **Classify** with `reference/signatures.md`: `noise` (ignore), `load` (startup, XML/defs),
   `runtime` (tick/draw/window exceptions), `save` (load/save), `perf` (spam). The parser already
   buckets noise; the table shows the rest ranked by severity then count.
4. **Attribute.** The `mods` column lists evidence in reliability order:
   `source:<Mod name>` / `pfid:<id>` (RimWorld's own `[Source:]`/`[File:]` lines — trust these) →
   `tag:<X>` (mod's own `[X]` log prefix) → `ns:<Namespace>` (first non-engine stack frame) →
   `harmony:<X>` (a Harmony patch was in the stack — the *patched* method's owner is shown; the
   patching mod is a suspect, not proof). Map a namespace or pfid to a mod with
   `list_installed_mods(package_ids=[...], detail=True)` or `workshop_mod_info([pfid])`.
5. **Repeats are diagnostic.** A per-tick `NullReferenceException` with count in the thousands is
   both the cause of TPS loss and of the log size; it outranks a one-off medium error.
6. **Hand off to the MCP tools** instead of re-deriving:
   - version mismatch, `MissingMethodException`, `TypeLoadException`, `ReflectionTypeLoadException`
     → `list_installed_mods(package_ids=[...])` (`version_ok`, advisories) and
     `check_mod_updates([pfid])`; a `replaced` advisory means switch to the maintained fork.
   - `Created WorkshopItem … no folder` → `check_mod_updates([pfid])`; Steam has not finished
     downloading or the folder was deleted.
   - missing dependency, `Could not find a type` from a framework → `diagnose_cycles()`
     (`missing_dependency` section) then `/rimworld-modpack`.
   - load-order symptoms (a patch applies before its target exists) → `sort_modlist()` dry run.
7. **Bisect when attribution fails.** `modlist_snapshot("before bisect")`, then with the user's
   yes `modlist_disable(<half of the non-framework mods>, dry_run=False)` (its
   `dependency_issues` show which remaining mods lose a requirement — take those out of the
   same half), relaunch, rerun the parser with `--since-startup`; repeat. Restore with
   `modlist_enable` of the `removed[]` from `modlist_diff("<snapshot id>", "current")`, then
   `sort_modlist(dry_run=False)`. Never edit `ModsConfig.xml` by hand.
8. **Report** in this order: what is actually broken (one line), which mod(s) and the evidence,
   the fix, then what was noise and can be ignored. If the user says a finding is expected,
   add it to `notes/accepted.md` (source = `Player.log`, key = signature + mod).

## Things that look scary but are not

`Fallback handler could not load library …MonoBleedingEdge/data-*.dll` (hundreds per launch),
`Texture … not multiples of 4`, `ThreadAbortException` on exit or scene change,
`Prepatcher:` timing lines, `Key binding conflict`, `Mod X dependency … needs <steamWorkshopUrl>`
(cosmetic unless the dependency is really absent), a single
`Cannot resolve dependency to assembly` during reflection-only load.

## Useful extra context

- `links/config/Mod_<pfid>_*.xml` — a mod's settings; a corrupt one breaks that mod's window
  (`Exception filling window for …Dialog_ModSettings`). Deleting it resets the mod (ask first).
- `links/game/Version.txt` — exact build; compare with a mod's `supportedVersions`.
- The parser's `first_line` values index into the file; use `sed -n 'N,Mp' links/logs/Player.log`
  for a small window around one, never the whole file.
