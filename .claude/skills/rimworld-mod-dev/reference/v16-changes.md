# What changed in 1.6 (and bites ported mods)

Sources: rimworldwiki "RimWorld 1.6 Mod Updates", Ludeon's 1.6 announcement; every row checked
against the installed game (1.6.4871) Defs or decompiled code — "Verified" says where. When a
ported mod errors, grep it for the left column.

## XML

| Old (≤1.5) | 1.6 | Verified |
|---|---|---|
| `ThingDef/placingDraggableDimensions` | `drawStyleCategory` (a `DrawStyleCategoryDef`) | 0 old uses in game Defs; `Verse.DrawStyleCategoryDef`; `def_lookup.py --uses drawStyleCategory` |
| `ThingDef/soundAmbient` (buildings) | comp `<li Class="CompProperties_AmbientSound"><sound>…</sound></li>` (`disabledOnUnpowered`, `disableOnHacked`, `disableOnInteracted`) | `RimWorld.CompProperties_AmbientSound`; `soundAmbient` still exists on projectile/ability props |
| `race/wildness` | stat: `<statBases><Wildness>0.75</Wildness></statBases>` | 0 old / 21 files with `<Wildness>`; `StatDefOf.Wildness` |
| — | `race/forceGender` (Male/Female) | `RaceProperties.forceGender` |
| — | `DamageDef/ignoreShields` | `DamageDef.ignoreShields` |
| `HediffDef/causesNeed` | removed: `HediffDef/chemicalNeed`, or `HediffStage/enablesNeeds` (list) | `HediffDef.chemicalNeed`, `HediffStage.enablesNeeds` |
| `HediffDef/disablesNeeds` | moved to `HediffStage/disablesNeeds` | `HediffStage.disablesNeeds` |
| `TerrainDef/holdSnow` | `holdSnowOrSand` | `TerrainDef.holdSnowOrSand` |
| `ThingDef/hideAtSnowDepth` (plants) | `hideAtSnowOrSandDepth` | `ThingDef.hideAtSnowOrSandDepth` |
| targetParams `canTargetMutants` | `canTargetSubhumans` | `TargetingParameters.canTargetSubhumans` |
| Scenario root | inherits abstract `ScenarioBase` (`ParentName="ScenarioBase"`) | Core `Scenarios/` defs |
| DLC list | + `Ludeon.RimWorld.Odyssey` (mod name `Odyssey`) | `Data/Odyssey` |
| `MayRequire` with `_steam` ids | now normalised (suffix ignored) everywhere | `ModLister.*NoSuffix` |
| About `modDependencies` | + `alternativePackageIds` list | `ModRequirement.alternativePackageIds` |

## C#

| Old | 1.6 | Verified |
|---|---|---|
| `Thing.Tick()` public, every tick | `protected virtual void Tick()` plus **`protected virtual void TickInterval(int delta)`** — things tick at a variable interval (1–15 ticks); `delta` = ticks covered | `Verse.Thing`, `ThingWithComps` |
| `ThingComp.CompTick()` | prefer `CompTickInterval(int delta)`; `CompTick/Rare/Long` still exist | `Verse.ThingComp` |
| `HediffComp.CompPostTick(ref float)` | + `CompPostTickInterval(ref float severityAdjustment, int delta)`; `Hediff.TickInterval(int delta)` | `Verse.HediffComp`, `Verse.Hediff` |
| `thing.IsHashIntervalTick(n)` | `IsHashIntervalTick(n, delta)` inside interval ticks | `Verse.Gen` |
| world tile `int` | `RimWorld.Planet.PlanetTile` struct (multiple planet layers: surface, orbit) — `Map.Tile`, caravans, quests, `Find.WorldGrid` | `RimWorld.Planet.PlanetTile` |
| Patching `FloatMenuMakerMap.AddHumanlikeOrders` | subclass `FloatMenuOptionProvider` (auto-discovered): override `Drafted`, `Undrafted`, `Multiselect`, `GetOptionsFor(Thing/Pawn, FloatMenuContext)` / `GetSingleOptionFor` | `RimWorld.FloatMenuOptionProvider`, wiki *Code_FloatMenuOptionProvider* |
| `Designator.DraggableDimensions` | `DrawStyleCategory` → `DrawStyleCategoryDef` | `Verse.Designator` |
| `ActiveDropPodInfo` | `ActiveTransporterInfo` | `RimWorld.ActiveTransporterInfo` |
| social `InteractionUtility` members | `SocialInteractionUtility` (`InteractionUtility` now holds `OrderInteraction`) | both files |
| `PawnsFinder.*TransportPods*` | `*Transporters*` (e.g. `AllMapsCaravansAndTravelingTransporters_Alive_Colonists`) | `RimWorld.PawnsFinder` (0 "TransportPods") |
| Krafs.Rimworld.Ref 1.5.* | `1.6.*` (resolves 1.6.4871 = this game build) | test build |
| Harmony | Harmony mod ships 0Harmony **2.4.1** (`links/workshop/2009463077/Current`) | file version |

New systems worth knowing before designing content: gravships and orbit/space maps (Odyssey),
`PlanetLayerDef`s, `TileMutatorDef`s/`LandmarkDef`s (Odyssey world gen), `PrefabDef` /
`LayoutRoomDef` structures, fishing, `PathGridDef`. Search them with
`def_lookup.py --grep . --type PlanetLayerDef` and `decompile.py`.

## Porting checklist

1. `grep -rE "placingDraggableDimensions|<soundAmbient>|<wildness>|causesNeed|<holdSnow>|hideAtSnowDepth|canTargetMutants" <mod>`.
2. `grep -rE "ActiveDropPodInfo|TransportPods|InteractionUtility\.|AddHumanlikeOrders|CompTick\(|\.Tile\b" <mod>/Source`.
3. `patch_check.py <mod> --active`, launch, `/rimworld-log-debug`.
4. Unknown names in the log (`doesn't correspond to any field`, `MissingMethodException`,
   `Could not find a type named`) → `decompile.py --grep <name>` to find the new home.
