# Testing and debugging a mod

## Before launching (offline, seconds)

1. `patch_check.py workspace/<Mod>` → 0 FAIL, 0 errors (add `--with <dep>` / `--active`).
2. `def_lookup.py <eachNewDef> --resolved --with workspace/<Mod>` — eyeball the merged def.
3. Field names you are unsure of: `decompile.py RimWorld.<DefType> --grep '\bfieldName\b'`.
4. C#: `dotnet build -c Release` with zero warnings you don't understand.

## Launch loop

- Deploy (copy to `links/mods/<Mod>`), enable via `modlist_enable` (dry run → user yes), sort.
  The game must be closed for ModsConfig writes and DLL replacement.
- Options → Gameplay → **Development mode**. Command line (Steam → Properties → Launch options):
  `-quicktest` (straight into a small test map), `-savedatafolder=<path>` (isolated config/saves
  — combine with `-quicktest` for a clean environment). A save named `autostart` loads
  automatically.
- Dev toolbar → **Debug actions**: *Spawn thing*, *Spawn pawn*, *Try place near thing*, *Add
  hediff*, *Execute incident*, *Change gene/xenotype*, *Set skill*, god mode (instant build),
  *Hot reload Defs* (General; re-reads XML into existing defs — fine for number tweaks, not for
  new defs, comps or C#). Custom `[DebugAction]`s from your assembly appear here too.
- Debug actions → *Output* category: tables for weapons, apparel, stats, recipes, xenotypes… —
  quick balance comparison with vanilla.
- Inspect: select a thing, the dev **inspector** (magnifier) shows fields; *Toggle job logging*,
  *Draw pawn debug*, *Draw lords/duties* for AI.
- Log window (dev mode, bottom-right) = Player.log. After any session:
  `python .claude/skills/rimworld-log-debug/scripts/parse_log.py --since-startup --mod <packageId>`.

## Startup errors → cause → fix

| Log text | Usual cause | Fix |
|---|---|---|
| `[mod] Patch operation X(xpath) failed` | xpath matches nothing (renamed def, missing mod, inherited field) | `patch_check.py -v`; guard or fix xpath |
| `XML error: <x> doesn't correspond to any field in type T` | wrong/old tag name, wrong nesting, missing `Class=` on an `li` | `decompile.py T`; `v16-changes.md` |
| `Could not find parent node named "X"` | typo, parent in a mod that loads later or isn't active | `def_lookup.py X`; `loadAfter` |
| `Could not resolve cross-reference to T named X` | defName typo, DLC/mod def without `MayRequire` | `def_lookup.py X --type T` |
| `Could not find a type named X` | `Class`/`thingClass`/`compClass` typo, namespace missing, DLL not loaded | `decompile.py X`; check Assemblies folder |
| `Duplicate XML node name X in this XML block` | two `<X>` siblings (often a patch Add on an existing key) | Replace instead of Add; Conditional |
| `Config error in X: …` | def's `ConfigErrors()` rule | `decompile.py <DefType> --grep ConfigErrors`, read the rule |
| `Mod X has multiple ThingDefs named Y` | duplicate defName in your mod | rename |
| `root element named …; should be named Defs` / `expected 'Patch'` | wrong root or file in wrong folder | move/rename root |
| `Texture … not multiples of 4` / pink squares | size, or wrong `texPath` / missing file | resize; check path under `Textures/` |
| `ReflectionTypeLoadException`, `MissingMethodException` | DLL built against another game build / missing dependency DLL | rebuild against `Krafs.Rimworld.Ref 1.6.*`; add dependency |
| `Patching exception in method …` / `HarmonyException` | patch target signature changed or ambiguous overload | `decompile.py <Type> --grep <Method>`; specify argument types |
| `Exception ticking …` (repeats) | NRE in comp/tick code | first frame in your namespace; null-guard |

Full signature catalogue and attribution rules: `.claude/skills/rimworld-log-debug/reference/signatures.md`.

## Compatibility testing

- With the user's full list: `patch_check.py <mod> --active` (≈25 s) catches patches that
  collide with other mods' patches (a node another mod removed/renamed earlier in load order).
- Known frameworks that change XML semantics: XmlExtensions / ModCheck custom operations
  (patch_check `SKIP`s them), Combat Extended (weapons/armor need CE patches), Humanoid Alien
  Races (`AlienRace.ThingDef_AlienRace`), Vanilla Expanded Framework (`VEF`/`VFECore`
  mod extensions). Look at how the target mod's own patches do it before inventing.
- Performance: Dubs Performance Analyzer (Workshop) for tick cost; keep `CompTickInterval`
  work cheap and `IsHashIntervalTick`-gated.
