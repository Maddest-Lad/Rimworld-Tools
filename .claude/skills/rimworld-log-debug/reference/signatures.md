# Player.log signature catalogue

Names match `SIGNATURES` in `scripts/parse_log.py`. Kinds: `noise` (bucketed, never listed),
`info` (bucketed), `load` (startup XML/def/assembly), `runtime`, `save`.

| Name | Pattern | Kind / sev | Meaning | Cause | Fix / handoff |
|---|---|---|---|---|---|
| `fallback_dll` | `Fallback handler could not load library …MonoBleedingEdge/data-*.dll` | noise | Mono probing transient native libs | engine | ignore |
| `thread_abort` | `ThreadAbortException` | noise | background thread cancelled | scene unload, exit, long-event cancel | ignore unless paired with a real failure |
| `texture_mult4` | `Texture '' has dimensions (w x h) which are not multiples of 4` | noise | can't GPU-compress texture | mod art | ignore; hundreds from one mod = that mod's whole texture set |
| `parsed_as_int` | `Parsed 0.3 as int.` | noise | float in int field | sloppy XML | ignore |
| `prepatcher` | `Prepatcher: …` | info | Zetrith's Prepatcher phases | normal | only for startup-time analysis |
| `keybind_conflict` | `Key binding conflict: A and B are both bound to K` | info | two commands share a hotkey | mods add keybinds | cosmetic |
| `dependency_no_url` | `Mod X dependency (pkg) needs to have <downloadUrl> and/or <steamWorkshopUrl>` | info | About.xml dependency lacks URL | author omission | only matters if the dependency is really missing → `list_installed_mods` |
| `workshop_no_folder` | `Created WorkshopItem for N but there is no folder for it` | load / medium | subscribed but not on disk | download pending, folder deleted | `check_mod_updates([N])` |
| `xml_unknown_field` | `XML error: <tag>…</tag> doesn't correspond to any field in type T` | load / high | unknown XML tag for that C# type | mod built for another version, typo; **cascades** | `[Source:]` names the mod → version check, `check_mod_updates` |
| `xml_error` | `XML error: …` (other) | load / high | malformed XML | stray `<`/`&`, bad patch | `[File:]` names the file |
| `xref_unresolved` | `Could not resolve cross-reference to T named D (wanter=field)` | load / medium | def references a missing def | removed dependency, load order, cascade from an XML error | resolve earlier load errors first; then `diagnose_cycles` missing deps |
| `type_not_found` | `Could not find a type named X` | load / high | XML references a C# type not loaded | missing/broken DLL dependency, outdated mod | dependency present? `list_installed_mods(detail=True)`, `check_mod_updates` |
| `def_not_found` | `Def named X not found` | load / medium | def missing | mod removed since save; defName typo | save-load: re-add the mod or accept loss |
| `duplicate_def` | `Duplicate defName …` | load / medium | same defName twice | two mods define it | real conflict; pick one, or Cherry Picker |
| `assembly_missing` | `Cannot resolve dependency to assembly 'X'` | load / low | managed assembly not preloaded | reflection-only probe (once = noise) or a mod DLL referencing a missing engine module | recurring → outdated mod |
| `reflection_typeload` | `ReflectionTypeLoadException` | load / high | assembly failed to load types | DLL compiled against old game/Unity API | outdated mod → `check_mod_updates`, `replaced` advisory |
| `missing_method` | `MissingMethodException` / `MissingFieldException` | runtime / high | method/field no longer exists | mod out of date vs. game or vs. another mod's API | update or disable that mod |
| `typeload` | `TypeLoadException` | load / high | CLR can't load a type | as above, or a Harmony patch targeting a changed signature | outdated mod |
| `exception_ticking` | `Exception ticking <thing>` | runtime / high | uncaught exception in tick loop | mod comp/patch NRE; fires every tick | top-frame mod; count tells spam |
| `exception_window` | `Exception filling window for <Class>` | runtime / medium | UI window threw | mod settings/dialog code; corrupt `Mod_*.xml` | class name pinpoints the mod |
| `exception_drawing` | `Exception drawing …` | runtime / medium | render-time throw | graphics/overlay mod | top-frame mod |
| `exception_jobdriver` | `Exception in JobDriver tick …` | runtime / medium | job AI threw | job/work mod | top-frame mod |
| `exception_loading_save` | `Exception loading …` / `Exception from asynchronous event` | save / high | save failed to load | removed mod, changed defs | `def_not_found` entries list what is missing |
| `save_load_error` | `Could not load reference to …` | save / medium | dangling reference in save | mod removed | usually survivable; warn |
| `harmony_exception` | `HarmonyException`, `Patching exception in method`, `Error while patching` | runtime / high | a Harmony patch failed to apply | patch targets a method that changed | the patching mod is outdated |
| `null_ref` | `NullReferenceException` (not in a more specific context) | runtime / high | NRE | any | top-frame mod |
| `generic_exception` | `…Exception:` at line start | runtime / medium | anything else | — | read the sample |
| `error_word` | line contains "error"/"exception" | runtime / low | catch-all | mod chatter | last resort; often benign |

## Stack-frame anatomy

```
Exception ticking Pawn_X: System.NullReferenceException: Object reference not set …
[Ref 1A2B3C4D]                                   ← Better Stack Traces id; later repeats say "Duplicate stacktrace"
  at BuggyMod.Comps.CompExplode.CompTick () [0x00012] in <hash>:0      ← first non-engine frame = suspect
  at Verse.ThingWithComps.Tick () [0x00020] in <hash>:0               ← vanilla
  at (wrapper dynamic-method) Verse.TickList.Tick_Patch1(Verse.TickList)  ← a Harmony patch on Verse.TickList.Tick was active
```

- Engine/vanilla namespaces skipped for attribution: `System.`, `UnityEngine.`, `Verse.`,
  `RimWorld.`, `HarmonyLib.`, `Mono.`.
- `_PatchN` / `DMD<…>` frames mean Harmony rewrote that method; the patch owner is not printed —
  correlate with mods that patch that class (search `links/workshop/<pfid>/**/*.dll` names or the
  mod's description).
- `[Source: Name] [File: path]` blocks under XML/cross-ref errors are RimWorld naming the mod
  (`Possible Matches:` lists every mod that touches the def; the first is usually the definer,
  the last patcher is usually the culprit).
