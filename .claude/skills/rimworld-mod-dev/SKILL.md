---
name: rimworld-mod-dev
description: Author, fix and port RimWorld 1.6 mods (Windows/Steam) - About.xml and folder layout, XML Defs and inheritance, PatchOperations/XPath patches for vanilla, DLC and other mods, MayRequire/LoadFolders compatibility, textures/sounds/translations, and C# assemblies (Krafs.Rimworld.Ref, Harmony, comps, settings). Verifies every field and API against the installed game with offline tools - def_lookup.py (find defs, vanilla precedent, resolved inheritance), patch_check.py (dry-run a mod's patches and lint its defs against the real def tree), decompile.py (ilspycmd-backed source lookup). Use when the user wants to create or change a mod, write or debug a patch, add content (weapons, xenotypes, genes, buildings, hediffs, factions), make a compatibility patch, update a mod to 1.6, or write Harmony/C# code.
---

# RimWorld 1.6 mod development

Game build here: `links/game/Version.txt` (1.6.4871). All helper scripts are read-only, need
lxml (system Python has it; otherwise `uv run --project rimworld-mcp python …`), and run from
the repo root:

```sh
S=.claude/skills/rimworld-mod-dev/scripts
python $S/def_lookup.py MeleeWeapon_Mace --resolved      # a def, its parent chain, merged XML
python $S/patch_check.py workspace/MyMod                  # dry-run patches + lint vs Core+DLC
python $S/decompile.py Verse.ThingComp                    # outline of a game type (C#)
```

## Ground rules

- **Verify, don't recall.** Training data mixes 1.0–1.5 and mod-specific fields. Before writing
  a tag, find it in a real 1.6 def (`def_lookup.py --uses <tag>` / `--class <Class>`) or in the
  C# field list (`decompile.py <Type>`); before calling an API, read its signature. The
  `reference/v16-changes.md` table lists the renames that bite most.
- **Copy vanilla precedent, then change it.** Find the closest vanilla def
  (`def_lookup.py --grep` / `--uses`), inherit from the same abstract parent, override only
  what differs. Vanilla XML is under `links/game/Data/<Core|Royalty|Ideology|Biotech|Anomaly|Odyssey>/Defs`.
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
   unique prefix (e.g. `AFUX_`) for every defName, Name, texture folder, Keyed key and Harmony id.
2. **Scaffold** (`reference/mod-structure.md`, `templates/`): `About/About.xml` (packageId:
   letters, digits and dots only, ≤60 chars), `supportedVersions` `1.6`, dependencies with
   `steamWorkshopUrl`, `loadAfter` for anything you patch; `1.6/` folder for version-specific
   content, `Common/` or root for shared; `LoadFolders.xml` only for conditional folders.
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
7. **C# if needed** (`reference/csharp.md`): copy `templates/csharp/Source/MyMod`, rename,
   `dotnet build -c Release` → `1.6/Assemblies/`. Add `brrainz.harmony` as a dependency if you
   use Harmony. Check every override/patch target with `decompile.py`.
8. **Deploy + test** (`reference/debugging.md`): copy to `links/mods/<Mod>`, enable via MCP
   (user go-ahead), launch with dev mode, spawn/test with debug actions, then run
   `/rimworld-log-debug` (`parse_log.py --mod <packageId>`) and fix everything attributed to you.
9. **Record** why decisions were made in the mod's README or `notes/decisions.md`.

## Porting a mod to 1.6

1. `supportedVersions` + a `1.6/` folder (or LoadFolders `v1.6`); older version folders stay.
2. `patch_check.py <mod> --active` — failing XPaths usually mean a vanilla def was renamed,
   moved to a DLC, or restructured; `def_lookup.py` the old name to see what exists now.
3. Grep the mod for every "old" name in `reference/v16-changes.md` (XML tags and C# APIs).
4. C#: retarget `Krafs.Rimworld.Ref` to `1.6.*`, rebuild, fix compile errors against
   `decompile.py` (ticks became `TickInterval(int delta)`, world tiles are `PlanetTile`, float
   menus use `FloatMenuOptionProvider`, …). A DLL that "loads" can still throw
   `MissingMethodException` at runtime — test every feature.
5. Launch, `/rimworld-log-debug`, repeat.

## Script reference

| Need | Command |
|---|---|
| Def by defName or Name, parent chain | `def_lookup.py X` (`--type ThingDef` to narrow) |
| Final merged XML | `def_lookup.py X --resolved` (+ `--patched` + `--active`) |
| Defs whose name matches | `def_lookup.py --grep 'Gun_.*Rifle' --type ThingDef` |
| Who uses a tag / comp class / worker class | `--uses drawStyleCategory`, `--class CompProperties_Refuelable` |
| Arbitrary query | `--xpath 'Defs/GeneDef[biostatArc>0]'` (prints owning defs) |
| Dry-run a mod's patches | `patch_check.py <dir|packageId|name>` (`-v` = passing ops too, `--json`) |
| Against a dependency / the full list | `--with <mod>` (repeatable) / `--active` |
| C# type outline / whole file / grep | `decompile.py Pawn_HealthTracker` / `--full` / `--grep AddHediff` |
| Search all game code | `decompile.py --grep 'class \w+ : ThingComp\b' --limit 100` |
| Another assembly (a mod's DLL) | `decompile.py --dll links/workshop/<pfid>/1.6/Assemblies/X.dll Type` |

Emulation notes: patch_check mirrors the game's load folders, file shadowing, `<Defs>`
merge order, all 13 vanilla PatchOperation classes incl. `success`, Sequence abort and
MayRequire on `li`, and XmlInheritance's merge/parent-lookup rules. Custom operation classes from
other mods (XmlExtensions, ModCheck, …) are reported as `SKIP`, not evaluated. It does not
cross-reference defNames or check fields against C# types — the game's `XML error: … doesn't
correspond to any field` still needs a launch (or `decompile.py <Type>` to check field names).

## References

- `reference/mod-structure.md` — folders, About.xml, LoadFolders, versions, publishing
- `reference/xml-defs.md` — def anatomy, inheritance, lists, references, common def types
- `reference/patching.md` — PatchOperations, XPath, MayRequire, conditional compatibility
- `reference/v16-changes.md` — 1.6 renames/removals (XML + C#)
- `reference/csharp.md` — project setup, Mod/Settings, comps, components, DefOf, Harmony
- `reference/assets.md` — textures, graphic classes, masks, sounds, translations
- `reference/debugging.md` — dev mode, testing, common load errors and fixes
- `reference/sources.md` — where each fact came from
