---
name: rimworld-mod-dev
description: Author, fix and port RimWorld 1.7 mods (Windows/Steam, Waylith engine on .NET 10) - About.xml and folder layout, XML Defs and inheritance, PatchOperations/XPath patches for vanilla, DLC and other mods, MayRequire/LoadFolders compatibility, textures/sounds/translations, GLSL ShaderDefs and MaterialDefs, Workshop asset packs, and C# assemblies (net10 against the game DLLs or a net472 build shared with 1.6, Harmony 3, comps, settings). Verifies every field and API against the installed game with offline tools - def_lookup.py (find defs, vanilla precedent, resolved inheritance), patch_check.py (dry-run a mod's patches and lint its defs against the real def tree), decompile.py (ilspycmd-backed source lookup) - and a -QuitAfterBoot startup smoke test. Use when the user wants to create or change a mod, write or debug a patch, add content (weapons, xenotypes, genes, buildings, hediffs, factions), make a compatibility patch, update a mod to 1.7 (or from older versions), or write Harmony/C# code.
---

# RimWorld 1.7 mod development

Game build here: `links/game/Version.txt` (1.7.4976, Steam `unstable` branch). All helper
scripts are read-only, need lxml (system Python has it; otherwise
`uv run --project rimworld-mcp python …`), and run from the repo root:

```sh
S=.claude/skills/rimworld-mod-dev/scripts
python $S/def_lookup.py MeleeWeapon_Mace --resolved      # a def, its parent chain, merged XML
python $S/patch_check.py workspace/MyMod                  # dry-run patches + lint vs Core+DLC
python $S/decompile.py Verse.ThingComp                    # outline of a game type (C#)
```

## Ground rules

- **Verify, don't recall.** Training data mixes 1.0–1.6 and mod-specific fields, and 1.7 changed
  the engine underneath. Before writing a tag, find it in a real def (`def_lookup.py --uses <tag>`
  / `--class <Class>`) or in the C# field list (`decompile.py <Type>`); before calling an API, read
  its signature. `reference/v17-changes.md` lists what 1.7 changed and the older renames that
  still bite.
- **Copy vanilla precedent, then change it.** Find the closest vanilla def
  (`def_lookup.py --grep` / `--uses`), inherit from the same abstract parent, override only
  what differs. Vanilla XML is under `links/game/Data/<Core|Royalty|Ideology|Biotech|Anomaly|Odyssey>/Defs`.
- **Stay above the engine.** Game/Verse APIs, defs and Harmony prefix/postfix survive engine
  changes; Unity internals, native code, Mono-only APIs, bundled 0Harmony and Prepatcher don't
  (`v17-changes.md` → What breaks).
- **Mods are developed in `workspace/<ModName>/`** and deployed as a copy to
  `links/mods/<ModName>/` (the game's local `Mods/` folder). Never write into `links/workshop`
  or `links/steam`. Deploying replaces files the game reads — confirm with the user first.
- **Activation goes through the MCP tools** (`modlist_enable` dry run → user yes → write; then
  `sort_modlist`), never by editing `ModsConfig.xml`. See `/rimworld-modpack`.
- **Decompiled game code is reference only** (gitignored `.cache/`): read it to learn APIs, write
  your own code. Same for other mods' source and RimSort (GPL): learn, never paste.
- Other mods' content is in `links/workshop/<pfid>/` — read it to patch it; never edit it.

## Workflow

1. **Scope.** XML-only (defs + patches) whenever possible; C# only for new behaviour. Pick a
   unique prefix (e.g. `AFUX_`) for every defName, Name, texture folder, shader file, Keyed key,
   assembly name and Harmony id.
2. **Scaffold** (`reference/mod-structure.md`, `templates/`): `About/About.xml` (packageId:
   letters, digits and dots only, ≤60 chars), `supportedVersions` `1.7` (+ `1.6` only if you
   test there), dependencies with `steamWorkshopUrl`, `loadAfter` for anything you patch; `1.7/`
   folder for version-specific content, `Common/` or root for shared; `LoadFolders.xml` only for
   conditional folders.
3. **Find precedent.** `def_lookup.py <defName|Name>` shows file:line and parent chain;
   `--resolved` shows what the game actually builds after inheritance; `--patched --active`
   includes the user's mods. `--xpath` answers "which defs have X".
4. **Write defs** (`reference/xml-defs.md`). New content = new defs with your prefix. Changing
   anything that exists = a patch, never a copy of the def.
5. **Write patches** (`reference/patching.md`). Target `Defs/Type[defName="X"]/…`, guard
   optional targets with `PatchOperationConditional` or `MayRequire` on Sequence `li`s, guard
   other mods with `PatchOperationFindMod` (mod *name*) or LoadFolders `IfModActive` (packageId).
6. **Check offline**: `patch_check.py workspace/<Mod>` (vanilla+DLC, seconds) — then with
   `--with <dependency>` for each mod you patch, or `--active` (the user's full list, ~25 s).
   Every `FAIL` is a red `Patch operation … failed` error in-game; fix all of them. Lints cover
   missing parents, duplicate nodes/defNames, bad defNames, description whitespace.
7. **C# if needed** (`reference/csharp.md`): copy `templates/csharp/Source/MyMod`, rename
   (namespace, `AssemblyName`, Harmony id), `dotnet build -c Release` → `1.7/Assemblies/` (the
   csproj references the game through `links/game`). Need the same DLL on 1.6? Use the net472
   variant in `csharp.md`. Add `brrainz.harmony` as a dependency if you use Harmony. Check every
   override/patch target with `decompile.py`.
8. **Deploy + test** (`reference/debugging.md`): copy to `links/mods/<Mod>`; quick load check with
   the `-QuitAfterBoot` smoke test; then enable via MCP (user go-ahead), launch with dev mode,
   spawn/test with debug actions, profile with the frame profiler, and run `/rimworld-log-debug`
   (`parse_log.py --mod <packageId>`); fix everything attributed to you.
9. **Art** for textures: `/rimworld-svg-art`. Custom visual effects: GLSL + `ShaderDef`
   (`reference/assets.md` → Shaders and materials).
10. **Publish** with the in-game uploader; it bakes asset packs (`mod-structure.md` → Asset
    packs). Keep source textures uploaded while you support 1.6.
11. **Record** why decisions were made in the mod's README or `notes/decisions.md`.

## Updating a mod to 1.7

1. Test it unchanged first: smoke test, then a play session; 1.6 mods normally just load (a
   `1.6/`-only mod loads `1.6/` on 1.7).
2. Grep for 1.7 risks (`v17-changes.md` → Porting checklist step 3): Prepatcher, native DLLs,
   bundled 0Harmony, transpilers, Unity APIs, asset-bundle shaders. Re-verify every transpiler
   against the 1.7 IL (`decompile.py`) and exercise every patched path in game.
3. Only fix demonstrated failures. Keep Scribe keys and save formats identical (saves travel
   between 1.6 and 1.7 both ways).
4. Then add `<li>1.7</li>` to `supportedVersions`; add a `1.7/` folder (or `<v1.7>` in
   LoadFolders.xml) only for files that must differ — e.g. a net10 assembly.
5. Mods from ≤1.5: also work through the rename tables and checklist in `v17-changes.md`;
   `patch_check.py <mod> --active` shows XPaths broken by renamed/moved vanilla defs. C#: rebuild
   per `csharp.md` and fix compile errors against `decompile.py` (ticks are
   `TickInterval(int delta)`, world tiles are `PlanetTile`, float menus use
   `FloatMenuOptionProvider`, …). A DLL that "loads" can still throw `MissingMethodException` at
   runtime — test every feature.

## Script reference

| Need | Command |
|---|---|
| Def by defName or Name, parent chain | `def_lookup.py X` (`--type ThingDef` to narrow) |
| Final merged XML | `def_lookup.py X --resolved` (+ `--patched` + `--active`) |
| Defs whose name matches | `def_lookup.py --grep 'Gun_.*Rifle' --type ThingDef` |
| Who uses a tag / comp class / worker class | `--uses drawStyleCategory`, `--class CompProperties_Refuelable` |
| Arbitrary query | `--xpath 'Defs/GeneDef[biostatArc>0]'` (prints owning defs) |
| Shader / material defs | `--grep . --type ShaderDef`, `--type MaterialDef` |
| Dry-run a mod's patches | `patch_check.py <dir|packageId|name>` (`-v` = passing ops too, `--json`) |
| Against a dependency / the full list | `--with <mod>` (repeatable) / `--active` |
| C# type outline / whole file / grep | `decompile.py Pawn_HealthTracker` / `--full` / `--grep AddHediff` |
| Search all game code | `decompile.py --grep 'class \w+ : ThingComp\b' --limit 100` |
| Another assembly (a mod's DLL, the engine) | `decompile.py --dll links/workshop/<pfid>/1.7/Assemblies/X.dll Type`, `--dll links/game/UnityStubs.dll` |

Emulation notes: patch_check mirrors the game's load folders, file shadowing, `<Defs>`
merge order, all 13 vanilla PatchOperation classes incl. `success`, Sequence abort and
MayRequire on `li`, and XmlInheritance's merge/parent-lookup rules. Custom operation classes from
other mods (XmlExtensions, ModCheck, …) are reported as `SKIP`, not evaluated. It does not
cross-reference defNames or check fields against C# types — the game's `XML error: … doesn't
correspond to any field` still needs a launch (the smoke test is enough) or `decompile.py <Type>`.

## References

- `reference/mod-structure.md` — folders, About.xml, LoadFolders, versions, publishing, asset packs
- `reference/xml-defs.md` — def anatomy, inheritance, lists, references, common def types
- `reference/patching.md` — PatchOperations, XPath, MayRequire, conditional compatibility
- `reference/v17-changes.md` — what 1.7 changed, what breaks, ≤1.5 renames (XML + C#)
- `reference/csharp.md` — 1.7 / dual-version builds, Mod/Settings, comps, components, DefOf, Harmony
- `reference/assets.md` — textures, graphic classes, masks, sounds, shaders/materials, translations
- `reference/debugging.md` — dev mode, smoke test, frame profiler, common load errors and fixes
- `reference/sources.md` — where each fact came from
