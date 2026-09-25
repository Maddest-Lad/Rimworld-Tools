# XML Defs

Verified against `Verse.XmlInheritance`, `DirectXmlToObjectNew`, `LoadedModManager`,
`DefDatabase`, `Def.ConfigErrors` in 1.6.4871.

## Anatomy

```xml
<?xml version="1.0" encoding="utf-8"?>
<Defs>                                            <!-- root must be <Defs> -->
  <ThingDef ParentName="BaseMeleeWeapon_Blunt_Quality">   <!-- element name = C# def type -->
    <defName>MYMOD_Sledgehammer</defName>         <!-- unique per def type; [A-Za-z0-9_-] only -->
    <label>sledgehammer</label>                   <!-- lower case; no [ ] { } -->
    <description>A heavy hammer.</description>    <!-- no leading/trailing whitespace -->
    <graphicData>
      <texPath>MyMod/Weapons/Sledgehammer</texPath>   <!-- under Textures/, no extension -->
      <graphicClass>Graphic_Single</graphicClass>
    </graphicData>
    <statBases><Mass>4</Mass><WorkToMake>10000</WorkToMake></statBases>
    <tools>
      <li><label>head</label><capacities><li>Blunt</li></capacities>
          <power>18</power><cooldownTime>2.5</cooldownTime></li>
    </tools>
  </ThingDef>
</Defs>
```

- A child element name is a **C# field name** of that type (case-sensitive). Unknown names give
  `XML error: <x> doesn't correspond to any field in type T` at startup. Check with
  `decompile.py RimWorld.ThingDef --grep 'public .* fieldName'` or find the tag in vanilla
  (`def_lookup.py --uses fieldName`). `IgnoreIfNoMatchingField="True"` silences one element (for
  fields that exist only in some versions / with some mod).
- `Class="Namespace.Type"` on a def node or an `li` selects a subclass
  (`<li Class="CompProperties_Glower">`, `<ThingDef Class="MyMod.MyThingDef">`). Namespace may be
  omitted for RimWorld/Verse types. Attributes are **not inherited** (the child's attributes
  replace the parent's), so repeat `Class` on the child if needed.
- Values: numbers use `.` decimals; bools `true`/`false`; enums by name (`<techLevel>Industrial`);
  `IntRange`/`FloatRange` as `1~3`; `IntVec2` as `(1,2)`; colours as `(0.5, 0.2, 0.1)` or
  `(128,51,25,255)`; `Type` fields by class name; def references by defName.
- Def references resolve after loading: a wrong defName is `Could not resolve cross-reference to
  T named X`. Use your prefix for new defNames, exact vanilla names for references.

## Inheritance

`Name="X"` registers a node as parent; `ParentName="X"` inherits from it; `Abstract="True"`
means "template only, never a def" (checked on the node itself — children are real defs unless
they also say `Abstract`). Parents must be the same element type in practice (the merge is by
node name).

Merge rules (`RecursiveNodeCopyOverwriteElements`):

| Child has | Result |
|---|---|
| a text value (`<Mass>4</Mass>`) | replaces the parent's value |
| a non-`li` element the parent also has | merged recursively (so `statBases` keeps unlisted parent stats) |
| a new element | appended |
| `li` items | **appended** to the parent's list — lists never replace by default |
| `Inherit="False"` on an element | replaces that element's content entirely (use to drop parent list items) |
| an empty element (`<comps />`) | keeps the parent's children if it had any |

Parent lookup is scoped: your own mod's `Name` first, else the nearest **earlier** mod in load
order, else official content. Two nodes with the same `Name` in one mod is an error; in
different mods, each mod sees its own. Missing parent → `Could not find parent node named "X"`.
`def_lookup.py <defName> --resolved` prints exactly the merged result.

Patches run **before** inheritance: patching an abstract parent affects every child that does
not override that field; a field a def only *inherits* cannot be targeted on the child (it isn't
in the child's XML) — patch the parent, or add the field to the child.

## Lists and "dictionaries"

- Plain lists: `<li>` per item. For def lists (`<thingCategories><li>Foo</li>`), items can carry
  `MayRequire="pkg.id"` — the entry is dropped quietly when the mod is absent.
- Keyed lists written as elements: `statBases`, `equippedStatOffsets`, `costList`,
  `skillRequirements`, `xenotypeChances`, `capacityFactors`… use `<DefName>value</DefName>`.
  Duplicate keys in one block are an error (`Duplicate XML node name`); add with a patch on the
  parent node, or Replace the existing key.
- `comps` / `modExtensions` are lists of objects: `<li Class="…">fields</li>`; a bare
  `<li><compClass>CompQuality</compClass></li>` uses the base `CompProperties`.

## Conditional content

- `MayRequire="Ludeon.RimWorld.Biotech"` on a top-level def: skipped unless all listed mods are
  active (comma list; `MayRequireAnyOf` = any). Also on list `li`s and def-reference elements
  (there it only suppresses the missing-reference error). Case-insensitive, `_steam`-agnostic.
- Whole files per mod: LoadFolders `IfModActive` (see `mod-structure.md`).

## Def load facts

- Same defName+type twice in one mod → error, extras skipped. Same defName in a later mod →
  silently replaces the earlier def entirely (don't do this; patch).
- `DefDatabase<T>` lookup is by defName; `defName` must match `^[a-zA-Z0-9\-_]*$`.
- ConfigErrors (`Config error in X: …` at startup) come from each def's `ConfigErrors()`; read it
  with `decompile.py <DefType> --grep ConfigErrors -A` / `--full` to see the rule you broke.

## Common def types (count in Core+DLC → a file to copy from)

| Type | # | Look at |
|---|---|---|
| ThingDef (items, weapons, apparel, buildings, plants, races) | 2055 | `Core/Defs/ThingDefs_Misc/Weapons/*.xml`, `ThingDefs_Buildings/`, `ThingDefs_Items/`, `ThingDefs_Races/` |
| HediffDef | 345 | `Core/Defs/HediffDefs/` |
| ThoughtDef | 934 | `Core/Defs/ThoughtDefs/` |
| RecipeDef (or `recipeMaker` on the ThingDef) | 214 | `Core/Defs/RecipeDefs/` |
| ResearchProjectDef | 168 | `Core/Defs/ResearchProjectDefs/` |
| PawnKindDef | 333 | `Core/Defs/PawnKindDefs_Humanlikes/`, `PawnKinds/` |
| FactionDef | 39 | `Core/Defs/FactionDefs/` |
| GeneDef / XenotypeDef | 203 / 12 | `Biotech/Defs/GeneDefs/`, `Biotech/Defs/GeneDefs/XenotypeDefs.xml` |
| AbilityDef | 107 | `Royalty/Defs/AbilityDefs/`, `Biotech/Defs/AbilityDefs/` |
| TraitDef | 51 | `Core/Defs/TraitDefs/` |
| JobDef / WorkGiverDef | 321 / 154 | `Core/Defs/JobDefs/`, `WorkGiverDefs/` (need C# drivers for new behaviour) |
| TerrainDef | 138 | `Core/Defs/TerrainDefs/` |
| IncidentDef / GameConditionDef | 139 / 38 | `Core/Defs/Storyteller/`, `GameConditionDefs/` |
| PreceptDef | 223 | `Ideology/Defs/PreceptDefs/` |
| DamageDef | 53 | `Core/Defs/DamageDefs/` |
| SoundDef | 1233 | `Core/Defs/SoundDefs/` |
| BackstoryDef | 845 | `Core/Defs/BackstoryDefs/` |

`def_lookup.py --grep . --type XenotypeDef --limit 100` lists any type; the mod-dev task starts
by opening the closest vanilla example with `def_lookup.py <defName> --resolved`.

## Frequent recipes

- **Craftable item**: inherit the matching abstract base (e.g. `BaseMeleeWeapon_Blunt_Quality`,
  `BaseHumanMakeableGun`, `ApparelMakeableBase`), add `recipeMaker` (`researchPrerequisite`,
  `recipeUsers`, `skillRequirements`), `costList` or `stuffCategories`+`costStuffCount`.
- **Raider gear**: `weaponTags` / `apparel.tags` must match a PawnKindDef's `weaponTags` /
  `apparelTags`.
- **Xenotype in factions** (Biotech): `FactionDef/xenotypeSet/xenotypeChances/<X>0.05</X>`;
  pawn kinds override with their own `xenotypeSet`. Create missing nodes with Conditional +
  `nomatch` Add before adding keys (see `patching.md`).
- **Gene**: copy a GeneDef of the same kind (`def_lookup.py --uses biostatMet --type GeneDef`),
  keep `biostatCpx/Met/Arc` balanced, set `displayCategory`, `iconPath`.
- **Research**: `ResearchProjectDef` with `baseCost`, `techLevel`, `prerequisites`, `tab`,
  `researchViewX/Y` (no overlaps in the tab).
