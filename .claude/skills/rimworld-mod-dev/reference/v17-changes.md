# What 1.7 (Waylith) changes for mods — and the ≤1.5 renames that still bite

1.7 replaced Unity with Ludeon's **Waylith engine** and Mono with **.NET 10** while keeping the
mod-facing game API. Sources: Ludeon's announcement (2026-10-12), HarmonyRimWorld 3.0.0.0 release
notes, and the installed 1.7.4976 game: a member-level diff of the decompiled 1.6.4871 and
1.7.4976 `Assembly-CSharp.dll`, the Waylith/UnityStubs assemblies, `RimWorld.runtimeconfig.json`,
and launches with test mods (see `sources.md`).

## What a mod needs

| Mod type | 1.7 action |
|---|---|
| XML only (defs, patches, textures, sounds) | Nothing. Test, then add `<li>1.7</li>` to `supportedVersions` (until then the mod list shows it yellow, "not made for this version"). |
| C# against the game API (comps, defs, Harmony prefix/postfix) | Usually nothing: a 1.6 DLL (net472, Krafs.Rimworld.Ref 1.6, Lib.Harmony 2.4) loads from `1.6/Assemblies` on 1.7 and its patches apply under Harmony 3 — verified. Rebuild for 1.7 only to use .NET 10 / modern C# (`csharp.md`). |
| Harmony transpilers, reflection on private members | Re-verify every one against the 1.7 IL (`decompile.py`): the game was recompiled for .NET 10, so e.g. string building now compiles to interpolated-string handlers and span-based `String.Concat`. A transpiler that "loads" may silently no longer match. |
| Unity-level code: native DLLs, Unity native plugins, custom Unity shaders/asset bundles, `UnityEngine` APIs beyond what the game uses, Prepatcher, preloaders, bundled 0Harmony | Expect breakage; see "What breaks". |

`supportedVersions`: add 1.7 only after testing; keep 1.6 if the same files still work there.
A mod with only a `1.6/` folder (or `LoadFolders.xml` with only `<v1.6>`) loads that on 1.7 —
the "newest version folder not newer than the game" rule is unchanged.

## Engine and install layout

| | 1.7 |
|---|---|
| Executable | `RimWorld.exe` (process name), host `RimWorld.dll`; no `RimWorldWin64_Data/` |
| Runtime | .NET 10 CoreCLR fork (`RimWorld.runtimeconfig.json`: `Microsoft.NETCore.App 10.0.10-waylithclr.dev`) with compatibility switches: lax assembly binding and member signatures, skipped access checks, Mono-compatible `string.GetHashCode` and float formatting, `UnityEngine*`/`Unity.*`/`Assembly-CSharp-firstpass` redirected to `UnityStubs.dll`, `JitPatchableAssemblies=Assembly-CSharp` (game methods are never inlined, so tiny methods are patchable) |
| Game code | `Assembly-CSharp.dll` at the install root, targets `net10.0`; Unity API surface in `UnityStubs.dll` + `Waylith.UnityCompat.dll`; engine in `Waylith*.dll` / `Brutal.*.dll` |
| Rendering | Vulkan. Shaders are GLSL (`Data/Core/Shaders/{Map,World}/*.glsl`, `Rendering/Shaders/`) compiled to SPIR-V and declared as `ShaderDef`s; caches in `<save data>/ShaderCache`, `TextureCache` |
| Vanilla assets | Core: `Assets.zip` (zstd; `Resources/Textures/**.dds` BC7, `Resources/Sounds/**.ogg`); DLC: `Data/<DLC>/Assets.zip` (`Textures/`, `Sounds/`). No Unity asset bundles |
| Steam API | `steam_api64.dll` at the install root |
| Log | `%USERPROFILE%\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Logs\Player.log` (+ `Player-prev.log`, Harmony's `harmony.log.txt`), timestamped `LEVEL [Category]` entries with a stack under each (`/rimworld-log-debug`) |
| Harmony | Harmony mod 3.0.0.0 loads **Harmony 3** for .NET 10 from its `1.7/` folder (1.6 keeps 2.4.3); stack traces list patch owners |
| Startup | parallel texture/audio prefetch while defs load (vanilla + all DLC: ~15 s to the main menu on this machine) |

## Game API changes (1.6.4871 → 1.7.4976)

The public surface is nearly identical: no def, comp, job, tick, Scribe, pathfinding or patching
API changed. Loader classes (`PatchOperation*`, `XmlInheritance`, `DefDatabase`, `ModLoadFolders`,
`DirectXmlToObject`) are unchanged apart from message formatting.

| Area | Change |
|---|---|
| New def types | `Verse.ShaderDef` (GLSL program + pipeline state, `assets.md` → Shaders) and `Verse.MaterialDef` (shader + named `textures`/`floats`/`colors`/`vectors`/`keywords`); vanilla: `Data/Core/Defs/ShaderDefs`, `MaterialDefs`. `ShaderTypeDef` still exists: its `shaderPath` (`Map/Cutout`) resolves to the `ShaderDef` named after the last segment (`Cutout`) |
| `GraphicData` | + `textureRepeats` (wrap mode Repeat), `borderMipMaps` (mips keep a clear border; also read by the asset-pack baker) |
| Lighting | `GlowGrid.RegisterCustomGlower(cell, radius, ColorInt, overlightRadius, …)` → handle; `DeregisterCustomGlower(handle)` — glow without a `CompGlower` thing |
| Sounds | `AudioGrain.forceToMono`; `Sample.startFrame`. Audio loads through `AudioClip.LoadFromFile` (`RuntimeAudioClipLoader` namespace removed) |
| Mods / Workshop | `ModMetaData.uploadBuildAssetPack` (default true), `uploadSkipSourceTextures`, `workshopUploadDirectoryOverride`; `ModContentPack.AllLoadFolders(...)`, `FirstAssetPackVersion` (1.7); `ModContentLoader<T>.PrefetchPaths` (`mod-structure.md` → Asset packs) |
| Dev tools | `Verse.ProfilerUI`: Debug actions → General → **Frame profiler** (flame chart, per-assembly/per-Harmony-patch instrumentation, allocations, VRAM) |
| `GenCollection.MaxBy/MinBy` | no longer extension methods: in 1.7 builds `list.MaxBy(f)` binds to `System.Linq.Enumerable.MaxBy`, which returns `null` on an empty reference-type sequence (Verse's throws). Call `GenCollection.MaxBy(list, f)` for the old behaviour. Existing DLLs are unaffected |
| Removed | `System.Collections.Generic.PriorityQueue` polyfill in Assembly-CSharp (use .NET's), Burst-compiled helpers (internal), `SteamDeck.IsVR` |
| Texture atlas internals | `StaticTextureAtlas` / `GlobalTextureAtlasManager` signatures now name `UnityEngine.Texture2D` explicitly, with Waylith overloads; atlases are cached to disk (`TextureCache`) |
| Misc | `Building_Door.SnapshotWillCloseSoonForJobs()` (door state for off-thread job checks), `CameraDriver.MyCamera` public, `Rand.InsideUnitSphere`, `Prefs` window position/fullscreen mode |

Threading: no new thread-safety contract. The same systems as 1.6 run off the main thread;
gameplay state stays main-thread-only.

## What breaks on 1.7

| Mod does | Result | Fix |
|---|---|---|
| Uses **Prepatcher** (`zetrith.prepatcher`) or depends on it | its assembly reloader targets Unity's Mono; first-day reports: menu without buttons, error cascades | disable; mods using `[PrepatcherField]` etc. need a replacement mechanism, mods that only used it as a Harmony provider depend on `brrainz.harmony` instead |
| Ships its own `0Harmony.dll` or a preloader (Doorstop) | `HARMONY LOADING PROBLEM` — older Harmony wins | never ship 0Harmony; depend on the Harmony mod |
| Native DLLs, P/Invoke into Unity's player, Unity native plugins | `DllNotFoundException` / `EntryPointNotFoundException` | needs a 1.7 build |
| Unity APIs the game never used | `UnityStubs` warning "Stub! You may not get expected results!" — call does nothing | use game/Verse APIs; check the stub list with `decompile.py --dll links/game/UnityStubs.dll --grep LogStub` |
| Custom Unity shaders/meshes in asset bundles | loaded only if the bundle has a Vulkan (SPIR-V) variant (a Linux build or one beside it), ≤512-byte uniforms, ≤8 storage buffers; else drawn with the default shader. Compressed/streamed meshes, unsupported prefab components are skipped | port the shader to GLSL + `ShaderDef`, or ship a Linux/Vulkan bundle |
| .NET Framework/Mono-only APIs (`Thread.Abort`, `AppDomain.CreateDomain`, reflection-only load, Remoting) | `PlatformNotSupportedException` | rewrite |
| Transpilers matching exact IL (local slots, offsets, `String.Concat` shapes) | "pattern not found", wrong code path or `InvalidProgramException` | match semantically (`CodeMatcher` on `Calls(method)`), re-read the 1.7 IL, or replace with prefix/postfix |
| Performance mods replacing engine/Unity hot paths (render-thread, FPS, GC tweaks) | no gain, regressions or errors | A/B test with and without; many are obsolete on Waylith |

Bidirectional saves: 1.6 saves load on 1.7 and 1.7 saves load on 1.6 — keep your Scribe keys
and formats unchanged so mod state survives both ways.

## Porting from ≤1.5 (1.6 renames, unchanged in 1.7)

Verified again in 1.7.4976 Defs and decompiled code. When an old mod errors, grep it for the
left column.

### XML

| Old (≤1.5) | Now | Verified |
|---|---|---|
| `ThingDef/placingDraggableDimensions` | `drawStyleCategory` (a `DrawStyleCategoryDef`) | 0 old uses in game Defs; `def_lookup.py --uses drawStyleCategory` |
| `ThingDef/soundAmbient` (buildings) | comp `<li Class="CompProperties_AmbientSound"><sound>…</sound></li>` (`disabledOnUnpowered`, `disableOnHacked`, `disableOnInteracted`) | `RimWorld.CompProperties_AmbientSound`; `soundAmbient` remains on projectile/ability props |
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
| `MayRequire` with `_steam` ids | normalised (suffix ignored) everywhere | `ModLister.*NoSuffix` |
| About `modDependencies` | + `alternativePackageIds` list | `ModRequirement.alternativePackageIds` |

### C#

| Old | Now | Verified |
|---|---|---|
| `Thing.Tick()` public, every tick | `protected virtual void Tick()` plus **`protected virtual void TickInterval(int delta)`** — things tick at a variable interval (1–15 ticks); `delta` = ticks covered | `Verse.Thing`, `ThingWithComps` |
| `ThingComp.CompTick()` | prefer `CompTickInterval(int delta)`; `CompTick/Rare/Long` still exist | `Verse.ThingComp` |
| `HediffComp.CompPostTick(ref float)` | + `CompPostTickInterval(ref float severityAdjustment, int delta)`; `Hediff.TickInterval(int delta)` | `Verse.HediffComp`, `Verse.Hediff` |
| `thing.IsHashIntervalTick(n)` | `IsHashIntervalTick(n, delta)` inside interval ticks | `Verse.Gen` |
| world tile `int` | `RimWorld.Planet.PlanetTile` struct (planet layers: surface, orbit) — `Map.Tile`, caravans, quests, `Find.WorldGrid` | `RimWorld.Planet.PlanetTile` |
| Patching `FloatMenuMakerMap.AddHumanlikeOrders` | subclass `FloatMenuOptionProvider` (auto-discovered): override `Drafted`, `Undrafted`, `Multiselect`, `GetOptionsFor(Thing/Pawn, FloatMenuContext)` / `GetSingleOptionFor` | `RimWorld.FloatMenuOptionProvider` |
| `Designator.DraggableDimensions` | `DrawStyleCategory` → `DrawStyleCategoryDef` | `Verse.Designator` |
| `ActiveDropPodInfo` | `ActiveTransporterInfo` | `RimWorld.ActiveTransporterInfo` |
| social `InteractionUtility` members | `SocialInteractionUtility` (`InteractionUtility` now holds `OrderInteraction`) | both files |
| `PawnsFinder.*TransportPods*` | `*Transporters*` (e.g. `AllMapsCaravansAndTravellingTransporters_Alive_Colonists`) | `RimWorld.PawnsFinder` |

Systems worth knowing before designing content: gravships and orbit/space maps (Odyssey),
`PlanetLayerDef`s, `TileMutatorDef`s/`LandmarkDef`s, `PrefabDef` / `LayoutRoomDef` structures,
fishing, `PathGridDef`. Search them with `def_lookup.py --grep . --type PlanetLayerDef` and
`decompile.py`.

## Porting checklist

1. `grep -rE "placingDraggableDimensions|<soundAmbient>|<wildness>|causesNeed|<holdSnow>|hideAtSnowDepth|canTargetMutants" <mod>`.
2. `grep -rE "ActiveDropPodInfo|TransportPods|InteractionUtility\.|AddHumanlikeOrders|CompTick\(|\.Tile\b" <mod>/Source`.
3. 1.7 runtime risks: `grep -rlE "Prepatcher|DllImport|0Harmony|Thread\.Abort|AppDomain\.Create|HarmonyTranspiler|AssetBundle" <mod>`,
   and list `Assemblies/` for native or bundled DLLs.
4. `patch_check.py <mod> --active`, launch (or `-QuitAfterBoot` smoke test, `debugging.md`),
   `/rimworld-log-debug`.
5. Unknown names in the log (`doesn't correspond to any field`, `MissingMethodException`,
   `Could not find a type named`) → `decompile.py --grep <name>` to find the new home.
