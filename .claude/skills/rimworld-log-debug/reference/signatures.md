# Player.log signature catalogue (1.7)

Names match `SIGNATURES` in `scripts/parse_log.py`. Kinds: `noise` (bucketed, never listed),
`info` (bucketed), `load` (startup XML/def/assembly), `runtime`, `save`. Signatures match the
message text (not the captured logging stack); entries no signature matches fall back to their
level: `ERROR`/`CRIT` → `logged_error`, `WARN` → `logged_warning` (engine categories →
`engine_warning`, info).

| Name | Pattern | Kind / sev | Meaning | Cause | Fix / handoff |
|---|---|---|---|---|---|
| `parsed_as_int` | `Parsed 0.3 as int.` | noise | float in int field | sloppy XML | ignore |
| `keybind_conflict` | `Key binding conflict: A and B are both bound to K` | info | two commands share a hotkey | mods add keybinds | cosmetic |
| `dependency_no_url` | `Mod X dependency (pkg) needs to have <downloadUrl> and/or <steamWorkshopUrl>` | info | About.xml dependency lacks URL | author omission | only matters if the dependency is really missing → `list_installed_mods` |
| `engine_warning` | `WARN` in an engine category (`Vulkan`, `GraphicsDevice`, `TextureResidency`, …) | info | platform chatter | driver/hardware | ignore unless a crash follows |
| `prepatcher` | `Prepatcher: …`, `Prepatcher.` frames, `zetrith.prepatcher` (all lines = one row) | load / high | Prepatcher is active | its assembly reloader targets Unity's Mono runtime, which 1.7 replaced | disable it; mods that hard-require it wait for a 1.7 release |
| `harmony_downgraded` | `HARMONY LOADING PROBLEM … Another Harmony library was loaded before the Harmony mod` | load / high | an older 0Harmony won the race | a mod bundling its own 0Harmony.dll, or a preloader | the log names the path; remove/update that mod |
| `crash` | `CRIT [Crash] === CRASH ===`, `Crash report written to:` | runtime / high | engine-level crash | GPU, memory, native code, runtime bug | read the report path; vanilla test |
| `gpu_or_memory_fatal` | `graphics device was lost`, `ran out of video/system memory` | runtime / high | device lost / OOM | driver, overclock, texture packs, huge list | update driver; trim texture mods |
| `workshop_no_folder` | `Created WorkshopItem for N but there is no folder for it` | load / medium | subscribed but not on disk | download pending, folder deleted | `check_mod_updates([N])` |
| `xml_unknown_field` | `XML error: <tag>…</tag> doesn't correspond to any field in type T` | load / high | unknown XML tag for that C# type | mod built for another version, typo; **cascades** | `[Source:]` names the mod → version check, `check_mod_updates` |
| `xml_error` | `XML error: …` (other) | load / high | malformed XML | stray `<`/`&`, bad patch | `[File:]` names the file |
| `xref_unresolved` | `Could not resolve cross-reference to T named D (wanter=field)` | load / medium | def references a missing def | removed dependency, load order, cascade from an XML error | resolve earlier load errors first; then `diagnose_cycles` missing deps |
| `type_not_found` | `Could not find a type named X` | load / high | XML references a C# type not loaded | missing/broken DLL dependency, outdated mod | dependency present? `list_installed_mods(detail=True)`, `check_mod_updates` |
| `def_not_found` | `Def named X not found` | load / medium | def missing | mod removed since save; defName typo | save-load: re-add the mod or accept loss |
| `duplicate_def` | `Duplicate defName …` | load / medium | same defName twice | two mods define it | real conflict; pick one, or Cherry Picker |
| `assembly_missing` | `Could not load file or assembly 'X'` | load / high | a referenced assembly isn't loaded | missing dependency mod, or a Mono/.NET Framework-only assembly | add the dependency or update the mod |
| `bad_image` | `BadImageFormatException` | load / high | DLL can't be loaded | 32-bit/mixed-mode/corrupt DLL | redownload or drop the mod |
| `reflection_typeload` | `ReflectionTypeLoadException` | load / high | assembly failed to load types | DLL compiled against an API that isn't there | outdated mod → `check_mod_updates`, `replaced` advisory |
| `native_missing` | `DllNotFoundException`, `EntryPointNotFoundException` | runtime / high | native code missing | mod ships native DLLs or P/Invokes Unity's player | needs a 1.7 build; disable |
| `platform_unsupported` | `PlatformNotSupportedException`, `… is not supported on this platform` | runtime / high | .NET Framework/Mono-only API (e.g. `Thread.Abort`) | mod not updated for .NET 10 | update or disable |
| `missing_method` | `MissingMethodException` / `MissingFieldException` | runtime / high | method/field no longer exists | mod out of date vs. game or vs. another mod's API | update or disable that mod |
| `typeload` | `TypeLoadException` | load / high | CLR can't load a type | as above, or a Harmony patch targeting a changed signature | outdated mod |
| `invalid_program` | `InvalidProgramException` | runtime / high | JIT rejected generated IL | a Harmony transpiler emits invalid IL | the patching mod (`patch:` evidence) is outdated |
| `harmony_exception` | `HarmonyException`, `Patching exception in method`, `Error while patching` | runtime / high | a Harmony patch failed to apply | patch targets a method that changed / transpiler pattern not found | the patching mod is outdated |
| `shader_def_unported` | `Shader def 'X' is not registered (no engine program ported yet); using engine default.` | load / low | a shader name with no GLSL program | mod's Unity shader not ported | cosmetic; tell the mod author |
| `shader_source_error` | `Shader 'X' reads/declares/vertex input …` | load / medium | a mod's GLSL shader failed reflection | bad `// @vertex` / `@default` annotations, mismatched varyings | author fixes the shader (`/rimworld-mod-dev`) |
| `assetbundle_unsupported` | `AssetBundle 'x': …` (shader can't be used, mesh/prefab/component not supported, texture not converted) | load / low | Unity asset partially loaded | bundle built for DX11 only, unsupported asset type | effect degrades; author ships a Linux (Vulkan) bundle or a `ShaderDef` |
| `assetbundle_failed` | `Failed to read AssetBundle`, `Unable to open archive file` | load / medium | bundle not loaded at all | corrupt/unsupported bundle | update/disable the mod |
| `unity_stub` | `X (File.cs:N): Stub! You may not get expected results!` (all lines = one row) | runtime / low | Unity API with no Waylith implementation was called | Unity-specific mod code | `ns:` names the caller; matters only if its feature is broken |
| `asset_decode` | `Texture decode failed`, `AudioClip '…' could not be decoded` | load / low | one asset unreadable | odd format/corrupt file | re-export the file |
| `exception_ticking` | `Exception ticking <thing>` | runtime / high | uncaught exception in tick loop | mod comp/patch NRE; fires every tick | top-frame mod; count tells spam |
| `exception_window` | `Exception filling window for <Class>` | runtime / medium | UI window threw | mod settings/dialog code; corrupt `Mod_*.xml` | class name pinpoints the mod |
| `exception_drawing` | `Exception drawing …` | runtime / medium | render-time throw | graphics/overlay mod | top-frame mod |
| `exception_jobdriver` | `Exception in JobDriver tick …` | runtime / medium | job AI threw | job/work mod | top-frame mod |
| `exception_loading_save` | `Exception loading …` / `Exception from asynchronous event` | save / high | save failed to load | removed mod, changed defs | `def_not_found` entries list what is missing |
| `save_load_error` | `Could not load reference to …` | save / medium | dangling reference in save | mod removed | usually survivable; warn |
| `null_ref` | `NullReferenceException` (not in a more specific context) | runtime / high | NRE | any | top-frame mod |
| `generic_exception` | `…Exception:` at line start | runtime / medium | anything else | — | read the sample |
| `logged_error` | any other `ERROR`/`CRIT` entry | runtime / medium | a mod or the game logged an error | — | read the sample; `ns:` = the caller |
| `logged_warning` | any other `WARN` entry outside engine categories | runtime / low | mod or game warning | — | usually benign |
| `error_word` | unstamped paste line containing "error"/"exception" | runtime / low | catch-all without a level | — | last resort |

## Stack-frame anatomy

```
2026-10-12 17:02:11.004 ERROR [Verse] Exception ticking Pawn_X: System.NullReferenceException: Object reference not set …
[Ref 1A2B3C4D]                                              ← HarmonyMod trace id (same id = same trace)
   at BuggyMod.Comps.CompExplode.CompTickInterval(Int32 delta) in D:\src\CompExplode.cs:line 12   ← first non-engine frame = suspect
   at Verse.ThingWithComps.TickInterval(Int32 delta)       ← vanilla
   at MonoMod.Utils.DynamicMethodDefinition.Verse.TickList.Tick_Patch1(TickList this)   ← Verse.TickList.Tick is Harmony-patched
    - POSTFIX other.tickmod: Verse.TickList.Tick <- Void OtherMod.Patches.TickList_Tick:Postfix(TickList __instance)   ← who patched it
    at Brutal.Logging.LogCategory.Error(...) [0x0]          ← logging call's stack (4 spaces, IL offset)
    at Verse.Log.Error(String text) [0x1C]
    at Verse.TickList.Tick() [0x1A2]
```

- Frames never blamed on a mod: `System.`, `Microsoft.`, `Brutal.`, `Waylith.`, `UnityEngine.`,
  `UnityStubs.`, `RimWorldWaylith.`, `Verse.`, `RimWorld.`, `LudeonTK.`, `HarmonyLib.`,
  `MonoMod.`, `HarmonyMod.`, `lambda_method`.
- `_PatchN` / `DMD<…>` frames mean Harmony rewrote that method; the `- PREFIX/POSTFIX/… <id>:`
  lines below the trace name every patch on it (the `<id>` is the patching mod's Harmony id,
  usually its packageId). A patch owner is a suspect when the exception is inside the patched
  method, not proof.
- `[Source: Name] [File: path]` blocks under XML/cross-ref errors name the mod
  (`Possible Matches:` lists every mod that touches the def; the first is usually the definer,
  the last patcher is usually the culprit).
- An `ERROR` whose logging stack shows a mod frame (`ns:`) means that mod called `Log.Error` —
  it reported the problem; read the message before blaming it.
