---
name: rimworld-log-debug
description: Diagnose errors and crashes in RimWorld 1.7's Player.log (Windows/Steam, Waylith engine on .NET 10). Use when the user pastes a RimWorld log or stack trace, reports red errors, a crash, a broken save, startup failures after changing mods, a mod that "worked on 1.6", or asks which mod is causing a problem. Streams and dedupes huge logs with scripts/parse_log.py, classifies known signatures (including 1.7 runtime breaks - Prepatcher, native DLLs, Unity stubs, asset-bundle shaders), attributes them to mods using stack frames and Harmony patch owners, and hands load-order and dependency issues to the rimworld-tools MCP tools.
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
| Only one mod's entries | `--mod <packageId, pfid, namespace, Harmony id or name fragment>` |
| Raw search inside entries | `--grep "<regex>"` |
| Better namespace / Harmony-id → packageId attribution | save `list_installed_mods(detail=True)` output to a file and pass `--mods-json <file>` |
| Some other log (pasted, uploaded) | positional `FILE`; unstamped fragments are grouped by line shape |

Logs live in `links/logs/` (= `%USERPROFILE%\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon
Studios\Logs\`): `Player.log`, `Player-prev.log` (rotated on each launch) and Harmony's
`harmony.log.txt`. `-savedatafolder` does not move them. The in-game log window shows the same
entries.

## The 1.7 log format

```
=== RimWorld by Ludeon Studios log ===          ← one session per launch
Started:   2026-10-12 16:56:37.387 -07:00
Runtime:   .NET 10.0.10-waylithclr.dev
Command:   "...\RimWorld.dll" -savedatafolder=... (launch options)

2026-10-12 16:56:38.757 ERROR [Verse] Created WorkshopItem for 3802032538 but there is no folder for it.
    at Brutal.Logging.LogCategory.Error(...) [0x0]       ← stack of the logging call, under EVERY entry
    at Verse.Log.Error(String text) [0x1C]
    at Verse.Steam.WorkshopItem.MakeFrom(PublishedFileId_t pfid) [0x31]   ← who logged it
```

- Level: `TRACE DEBUG INFO WARN ERROR CRIT`; category `[Verse]` = the game's `Log.*`,
  `[UnityDebug]` = a mod calling `UnityEngine.Debug.Log*`, `[UnityStubs]` = Unity API stub
  warnings, engine categories (`[Vulkan]`, `[GraphicsDevice]`, `[TextureResidency]`, …).
- Exception text inside a message uses .NET frames (`   at Ns.Type.Method(Type arg) in file:line N`,
  3 spaces); the captured logging stack uses 4 spaces and `[0xIL]`.
- With the Harmony mod, traces get `[Ref XXXXXXXX]` and, below them, one line per patch on a
  method in the trace: `    - PREFIX <harmony id>: Verse.Pawn.Tick <- Void Mod.Patch:Prefix(...)`.

## Triage flow

0. **Check `notes/accepted.md`** for signatures or mods already accepted; they go in the
   "noise" line of the report, not the findings.
1. **Run the parser.** Note the session header (game version, command line), the *first real
   error* and the top table. No session header = a pasted fragment or a pre-1.7 log.
2. **Runtime layer first.** A broken patch runtime makes every mod look broken (menu without
   buttons, a wall of red at startup). In this order: a `prepatcher` row (Prepatcher is
   Mono-only and breaks 1.7 — disable it), `native_missing` / `platform_unsupported` /
   `invalid_program` / `harmony_exception` rows, then confirm the Harmony mod is the current
   1.7 build (`check_mod_updates(["2009463077"])`; its `1.7/` folder ships Harmony 3). Only then
   blame content mods — the last mod named in a trace is often just the first to hit the broken
   runtime.
3. **Fix the first load error first.** RimWorld merges all XML into one document; a single
   `XML error` / `Could not find a type` cascades into dozens of unrelated-looking
   `cross-reference` and `Def named X not found` entries. Do not chase anything below the first
   `load`-kind error until it is resolved.
4. **Classify** with `reference/signatures.md`: `noise`/`info` (bucketed), `load` (startup,
   XML/defs/assemblies), `runtime` (tick/draw/window exceptions, logged errors/warnings), `save`.
   The table is ranked by severity then count.
5. **Attribute.** The `mods` column lists evidence in reliability order:
   `source:<Mod name>` / `pfid:<id>` / `local:<folder>` (`[Source:]`/`[File:]` lines — trust
   these) → `tag:<X>` (mod's own `[X]` prefix) → `ns:<Namespace>` (first non-engine frame, from
   the exception or the logging call) → `patch:<harmony id>` (HarmonyMod names a patch on a
   method in the trace — suspect, not proof) → `harmony:<X>` (a `_Patch`/`DMD<` frame: that
   vanilla method is patched) → `bundle:<file>` (asset bundle name). Map a namespace, Harmony id
   or pfid to a mod with `list_installed_mods(package_ids=[...], detail=True)` or
   `workshop_mod_info([pfid])`.
6. **Repeats are diagnostic.** A per-tick `NullReferenceException` with count in the thousands is
   both the cause of TPS loss and of the log size; it outranks a one-off medium error.
7. **Hand off to the MCP tools** instead of re-deriving:
   - `version_mismatch`, `MissingMethodException`, `TypeLoadException`, `ReflectionTypeLoadException`
     → `list_installed_mods(package_ids=[...])` (`version_ok`, advisories) and
     `check_mod_updates([pfid])`; a `replaced` advisory means switch to the maintained fork.
   - `Created WorkshopItem … no folder` → `check_mod_updates([pfid])`; Steam has not finished
     downloading or the folder was deleted.
   - missing dependency, `Could not find a type` from a framework → `diagnose_cycles()`
     (`missing_dependency` section) then `/rimworld-modpack`.
   - load-order symptoms (a patch applies before its target exists) → `sort_modlist()` dry run.
8. **Bisect when attribution fails.** `modlist_snapshot("before bisect")`, then with the user's
   yes `modlist_disable(<half of the non-framework mods>, dry_run=False)` (its
   `dependency_issues` show which remaining mods lose a requirement — take those out of the
   same half), relaunch, rerun the parser with `--since-startup`; repeat. Restore with
   `modlist_enable` of the `removed[]` from `modlist_diff("<snapshot id>", "current")`, then
   `sort_modlist(dry_run=False)`. Never edit `ModsConfig.xml` by hand. Startup-only problems
   bisect fast with `-QuitAfterBoot` (below).
9. **Report** in this order: what is actually broken (one line), which mod(s) and the evidence,
   the fix, then what was noise and can be ignored. If the user says a finding is expected,
   add it to `notes/accepted.md` (source = `Player.log`, key = signature + mod).

## 1.7 failure modes worth knowing

| Symptom | Usual cause | Action |
|---|---|---|
| Main menu without buttons, red cascade at startup | Prepatcher (Mono-only reloader) or an outdated Harmony | disable `zetrith.prepatcher`, update Harmony, retest with few mods |
| `DllNotFoundException` / `EntryPointNotFoundException` | mod ships a native DLL or calls into Unity's native player | mod needs a 1.7 build; disable it |
| `[UnityStubs] X: Stub! You may not get expected results!` | mod calls a Unity API Waylith doesn't implement | feature of that mod may silently do nothing; low severity unless the user sees breakage |
| `AssetBundle 'x': shader 'y' can't be used …` | bundle has no Vulkan/SPIR-V shader variant (Windows-only DX build) | mod's custom effect draws with the default shader; author must ship a Linux/Vulkan bundle or a `ShaderDef` |
| `Shader def 'X' is not registered … using engine default` | a `ShaderTypeDef`/`ShaderDef` name with no GLSL program | cosmetic; the mod's shader isn't ported |
| `PlatformNotSupportedException` (e.g. thread abort) | .NET Framework/Mono-only API | mod needs a 1.7 update |
| `InvalidProgramException`, transpiler "pattern not found" | Harmony transpiler emitted bad IL / no longer matches | patching mod is outdated |
| Performance mod gives no gain or regresses | it duplicates or fights Waylith internals | A/B test without it |
| Crash before mods load | old/unsupported GPU or driver (Vulkan) | vanilla test first; `CRIT [Crash]` entry names the report file |

## Startup smoke test (no clicking)

`RimWorld.exe -savedatafolder=<empty temp dir> -QuitAfterBoot` boots with a fresh config (Core +
owned DLC), writes `Logs/Player.log` and quits about 3 s after the main menu appears (vanilla 1.7:
~17 s). Put `<PrefsData><runInBackground>True</runInBackground></PrefsData>` in
`<temp>/Config/Prefs.xml` first — otherwise the game pauses while its window is unfocused and never
finishes. The temp folder's `ModsConfig.xml` selects the mods (same format as the real one; build
it with the user's yes, never edit theirs). Other switches: `-ScreenshotAfterBoot=<png>`,
`-Verbose` (engine trace), `-NoFileLogCallstacks` (smaller log), `-console`.

## Things that look scary but are not

Engine `INFO`/`WARN` lines (GPU selection, Vulkan layers, texture residency, `GpuProbe`), the
stack under every `INFO` entry, `Key binding conflict`, `Mod X dependency … needs
<steamWorkshopUrl>` (cosmetic unless the dependency is really absent), `Parsed 0.3 as int`,
`Created WorkshopItem … no folder` for a mod the user just unsubscribed.

## Useful extra context

- `links/config/Mod_<pfid>_*.xml` — a mod's settings; a corrupt one breaks that mod's window
  (`Exception filling window for …Dialog_ModSettings`). Deleting it resets the mod (ask first).
- `links/game/Version.txt` — exact build; compare with a mod's `supportedVersions` (1.6-only mods
  load on 1.7 and show yellow — not an error by itself).
- `links/logs/harmony.log.txt` — Harmony's own debug log (when a mod enables it).
- The parser's `first_line` values index into the file; use `sed -n 'N,Mp' links/logs/Player.log`
  for a small window around one, never the whole file.
