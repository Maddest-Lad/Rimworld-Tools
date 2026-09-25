# XML patching (PatchOperations)

Semantics from the decompiled `Verse.PatchOperation*` classes (1.6.4871); `patch_check.py`
emulates exactly these.

## Pipeline

1. Every active mod's `Defs` XML is concatenated (load order) under one `<Defs>` root.
2. Every active mod's `Patches/**/*.xml` operations run **in load order**, each against that
   whole document (so any mod's defs are visible; earlier mods' patches have already applied).
3. Inheritance resolves, MayRequire filters top-level defs, defs are built.

Patch files: root `<Patch>`, children `<Operation Class="…">` only (anything else is logged and
skipped). An operation that never succeeds logs `[<mod>] Patch operation <op>(<xpath>) failed`
+ `file:`. Exceptions inside an op log `Error in patch.Apply()`.

## Operations

| Class | Fields | Succeeds when | Effect |
|---|---|---|---|
| `PatchOperationAdd` | `xpath`, `value`, `order` = Append\|Prepend | xpath matched ≥1 | appends/prepends `value`'s children as **children** of each match. Does not replace an existing element → adding `<label>` twice makes a duplicate node error. |
| `PatchOperationInsert` | `xpath`, `value`, `order` = **Prepend** (default)\|Append | matched ≥1 | inserts `value`'s children as **siblings** before/after each match |
| `PatchOperationRemove` | `xpath` | matched ≥1 | removes each match |
| `PatchOperationReplace` | `xpath`, `value` | matched ≥1 | replaces each match with `value`'s children (any number, incl. zero); `…/text()` targets just the text |
| `PatchOperationAttributeAdd` | `xpath`, `attribute`, `value` | at least one match **lacked** the attribute | adds it where missing |
| `PatchOperationAttributeSet` | `xpath`, `attribute`, `value` | matched ≥1 | adds or overwrites |
| `PatchOperationAttributeRemove` | `xpath`, `attribute` | at least one match **had** it | removes it |
| `PatchOperationAddModExtension` | `xpath` (to defs), `value` | matched ≥1 | appends `value` children to `<modExtensions>`, creating it if absent |
| `PatchOperationSetName` | `xpath`, `name` | matched ≥1 | renames the element, keeps inner XML, **drops its attributes** |
| `PatchOperationSequence` | `operations` (`li Class="…"`) | every child succeeded | runs children in order, **stops at the first failure**; `li` may carry `MayRequire`/`MayRequireAnyOf` (skipped when not met) |
| `PatchOperationConditional` | `xpath`, `match`, `nomatch` | the branch taken succeeded (no branch taken: true if `match` exists, else whether `nomatch` exists) | runs `match` if xpath finds a node, else `nomatch` |
| `PatchOperationFindMod` | `mods` (`li` = mod **names**), `match`, `nomatch` | branch succeeded or no branch | tests `ModLister.HasActiveModWithName` — the `<name>` from About.xml (DLC: `Royalty`, `Biotech`…), **not** packageId |
| `PatchOperationTest` | `xpath` | matched ≥1 | obsolete; only useful inside Sequence as a gate. Use Conditional. |

Any operation also accepts `<success>Normal|Invert|Always|Never</success>` applied to its
result. `Always` hides genuine breakage — prefer Conditional/FindMod so failures stay visible.
`MayRequire` on a top-level `<Operation>` is **ignored** (the op runs anyway) — use it only on
Sequence `li`s, or use FindMod / LoadFolders.

## XPath

- Relative to the document: `Defs/ThingDef[defName="Gun_Revolver"]/statBases/Mass`
  (`/Defs/…` is equivalent). Case-sensitive. XPath 1.0 (no `ends-with`; use `contains`,
  `starts-with`, `substring`).
- Multiple defs: `Defs/ThingDef[defName="A" or defName="B"]`. Abstract parents:
  `Defs/ThingDef[@Name="BaseWeapon"]`.
- By content: `Defs/ThingDef[comps/li/@Class="CompProperties_Refuelable"]`,
  `Defs/HediffDef[contains(defName,"Implant")]`, `Defs/ThingDef[race/intelligence="Humanlike"]`.
- `li` by value: `…/weaponTags/li[text()="MedievalMeleeDecent"]`; by position `li[1]`.
- **Performance**: `//ThingDef` or `Defs//li` walks every node of every mod (tens of thousands of
  elements, for each operation). Anchor at `Defs/<Type>[defName=…]`; batch many defs into one op
  with `or`. patch_check warns on leading `//`.
- `text()` results: Replace works on text; Add/Insert on text is almost never what you want.

## Idioms

**Change a value**
```xml
<Operation Class="PatchOperationReplace">
  <xpath>Defs/ThingDef[defName="Gun_Revolver"]/statBases/Mass</xpath>
  <value><Mass>1.2</Mass></value>
</Operation>
```

**Add a value that may or may not exist (inherited or absent)** — the child's XML only contains
what it declares, so test first:
```xml
<Operation Class="PatchOperationConditional">
  <xpath>Defs/ThingDef[defName="Gun_Revolver"]/statBases/Beauty</xpath>
  <match Class="PatchOperationReplace">
    <xpath>Defs/ThingDef[defName="Gun_Revolver"]/statBases/Beauty</xpath>
    <value><Beauty>2</Beauty></value>
  </match>
  <nomatch Class="PatchOperationAdd">
    <xpath>Defs/ThingDef[defName="Gun_Revolver"]/statBases</xpath>
    <value><Beauty>2</Beauty></value>
  </nomatch>
</Operation>
```
Same pattern to create a missing container before adding into it (as in
`workspace/AFUXenotypes/Patches/AFUX_Factions_Core.xml`: ensure `xenotypeSet`, then
`xenotypeChances`, then Add the keys).

**Add a comp / mod extension**
```xml
<Operation Class="PatchOperationAdd">
  <xpath>Defs/ThingDef[defName="Sandbags"]/comps</xpath>
  <value><li Class="CompProperties_Glower"><glowRadius>3</glowRadius><glowColor>(217,112,33,0)</glowColor></li></value>
</Operation>
<Operation Class="PatchOperationAddModExtension">
  <xpath>Defs/ThingDef[defName="Sandbags"]</xpath>
  <value><li Class="MyMod.MyExtension"><bonus>2</bonus></li></value>
</Operation>
```
(If the def may have no `<comps>`, Conditional-create it first.)

**Remove a list entry**
```xml
<Operation Class="PatchOperationRemove">
  <xpath>Defs/ThingDef[defName="Gun_Revolver"]/weaponTags/li[text()="SimpleGun"]</xpath>
</Operation>
```

**Only if a DLC / mod is active** — three options, best first:
1. LoadFolders.xml `IfModActive="pkg.id"` folder holding these patches (no guard needed).
2. FindMod by mod name:
   ```xml
   <Operation Class="PatchOperationFindMod">
     <mods><li>Vanilla Factions Expanded - Empire</li></mods>
     <match Class="PatchOperationSequence"><operations>
       <li Class="PatchOperationAdd">…</li>
     </operations></match>
   </Operation>
   ```
3. Sequence `li MayRequire="Ludeon.RimWorld.Biotech"` (per operation, packageId-based).

A plain op targeting another mod's def with no guard **fails loudly** when that mod is absent —
always guard optional targets.

**Patch many defs at once** — one op with an `or` predicate or a structural predicate beats
dozens of ops; but a Sequence of independent edits fails as a unit, so don't bundle unrelated
changes into one Sequence (and a failing Sequence reports only
`lastFailedOperation=…`).

## Debugging patches

- `python .claude/skills/rimworld-mod-dev/scripts/patch_check.py workspace/<Mod> -v` — match
  counts for every op; FAIL lines are exactly the in-game errors. Add `--with <mod>` for each
  patched mod, or `--active` for the real list.
- `def_lookup.py <defName> --raw --patched --with workspace/<Mod>` — the def after all patches,
  before inheritance; `--resolved` for after.
- In-game: dev mode → debug actions → *Output* → def dumps; or read `Player.log` via
  `/rimworld-log-debug --grep "Patch operation"`.
