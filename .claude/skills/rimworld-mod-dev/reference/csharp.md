# C# for RimWorld 1.7

Everything here compiles and loads: `templates/csharp/Source/MyMod` builds against the 1.7.4976
game assemblies + Lib.Harmony 3.0.0-rc.2 with .NET SDK 10 (`dotnet build -c Release`), and test
mods built both ways below were launched on 1.7 (constructor, `[StaticConstructorOnStartup]`,
Harmony postfix all ran). Before overriding or patching anything, read the real signature:
`python .claude/skills/rimworld-mod-dev/scripts/decompile.py <Type> [--grep …]`.

## Project

1.7 runs on .NET 10 (Waylith's CoreCLR) and still loads .NET Framework 4.7.2 mod DLLs built for
1.6. Pick one of two builds:

| | 1.7-native (template default) | One DLL for 1.6 and 1.7 |
|---|---|---|
| `TargetFramework` | `net10.0`, `ImplicitUsings` off | `net472` |
| Game references | `$(RimWorldDir)\Assembly-CSharp.dll` + `UnityStubs.dll` from the install (`Private=false`); no 1.7 `Krafs.Rimworld.Ref` exists yet | `Krafs.Rimworld.Ref` `1.6.*` (publicized 1.6 reference assemblies) |
| Harmony | `Lib.Harmony` `3.0.0-rc.2`, `ExcludeAssets="runtime"` | `Lib.Harmony` `2.4.3`, `ExcludeAssets="runtime"` |
| Output | `<Mod>/1.7/Assemblies/` | `<Mod>/1.6/Assemblies/` (1.7 falls back to it) or `Common/Assemblies/` |
| Gains | modern BCL (`Span`, `Enumerable.MaxBy`, `PriorityQueue`, `System.Text.Json`, …), every C# feature | runs on the 1.6 main branch too |
| Limits | 1.7 only; private members need reflection (`AccessTools`, `Traverse`) — the references aren't publicized | .NET Framework API surface; `LangVersion latest` syntax works, features needing new runtime types don't |

A mod can ship both: `1.6/Assemblies` (net472) and `1.7/Assemblies` (net10) from two projects
or a multi-targeted one; each game version loads only its folder.

Common to both:

- `AssemblyName` unique per mod — two mod DLLs with the same assembly name load only once.
- **Never ship `0Harmony.dll`** — the Harmony mod (`brrainz.harmony`, Workshop 2009463077)
  provides Harmony 2.4.3 on 1.6 and Harmony 3 on 1.7; a bundled copy causes `HARMONY LOADING
  PROBLEM`. Don't compile against a newer Lib.Harmony than the mod ships if you use new APIs.
- Don't copy `Assembly-CSharp.dll`, `UnityStubs.dll` or `UnityEngine*` into `Assemblies/`.
- Referencing another mod's DLL: `<Reference Include="X"><HintPath>…\links\workshop\<pfid>\<ver>\Assemblies\X.dll</HintPath><Private>false</Private></Reference>`
  and add that mod to `modDependencies` + `loadAfter`. For an *optional* mod, avoid hard
  references (reflection, or a separate assembly in a LoadFolders `IfModActive` folder).
- No native DLLs, no P/Invoke into Unity's player, no Unity APIs the game doesn't use (many are
  stubs on 1.7 — they log once and do nothing).

Build: `dotnet build workspace/<Mod>/Source/<Proj> -c Release` (the template finds the game via
`links/game`; elsewhere `-p:RimWorldDir=<RimWorld folder>`). The game loads mod DLLs with
`Assembly.LoadFrom` and keeps them locked — close it before rebuilding/deploying.

## Startup order (what exists when)

1. `Mod` subclasses are constructed (**`LoadedModManager.CreateModClasses`**) — before any XML is
   loaded. Do: `GetSettings<T>()`, `new Harmony(id).PatchAll()`. Don't touch defs.
2. Defs XML merged → patches → inheritance → defs built → cross-references resolved →
   `[DefOf]` classes bound. Textures and sounds prefetch in parallel meanwhile.
3. `[StaticConstructorOnStartup]` static constructors run (main thread, all defs ready,
   textures loadable). Use for `ContentFinder<Texture2D>.Get(...)` into `static readonly`
   fields, def post-processing, caches. Keep them cheap and targeted — big modlists multiply
   every eager scan of all defs/types.

## Core patterns

| Need | Base type / API | XML hook |
|---|---|---|
| Behaviour on a Thing | `ThingComp` + `CompProperties` (set `compClass` in ctor) | `<comps><li Class="MyMod.CompProperties_X">` |
| Behaviour on a hediff | `HediffComp` + `HediffCompProperties` | `<comps>` on the HediffDef |
| Extra data on any def | `DefModExtension`; read with `def.GetModExtension<T>()` | `<modExtensions><li Class="MyMod.Ext">` |
| New def type | `class MyDef : Def` | `<MyMod.MyDef>` elements (or `<Defs><MyDef>` with namespace-less class if unique) |
| Def references in code | `[DefOf] public static class MyDefOf { public static ThingDef X; static MyDefOf() => DefOfHelper.EnsureInitializedInCtor(typeof(MyDefOf)); }` + `[MayRequireBiotech]` etc. on DLC fields | — |
| Per-save global state | `GameComponent` (ctor **must** be `(Game game)`), `GameComponentTick()` | auto-instantiated |
| Per-map state | `MapComponent` (ctor `(Map map)`), `MapComponentTick()` | auto |
| Per-world state | `WorldComponent` (ctor `(World world)`) | auto |
| Settings | `ModSettings` + `Mod.DoSettingsWindowContents(Rect)` / `SettingsCategory()`; file `Config/Mod_<modFolderName>_<ModClass>.xml` (renaming the folder "loses" settings) | — |
| Right-click menu | subclass `FloatMenuOptionProvider` (auto-discovered) | — |
| New job | `JobDriver` (`MakeNewToils`, `TryMakePreToilReservations`) + `JobDef` (`driverClass`) + `WorkGiver_Scanner` + `WorkGiverDef` | JobDef/WorkGiverDef |
| Custom thing class | `class MyBuilding : Building` | `<thingClass>MyMod.MyBuilding</thingClass>` |
| Gizmos | override `GetGizmos()` / `CompGetGizmosExtra()`; `Command_Action`, `Command_Toggle` | — |
| Light without a glower thing | `map.glowGrid.RegisterCustomGlower(cell, radius, color, overlightRadius, …)` → handle; `DeregisterCustomGlower(handle)` (1.7) | — |
| Custom material/shader | `MaterialDef` / `ShaderDef` (`assets.md` → Shaders and materials); `def.Material` | Defs |
| Debug actions | `using LudeonTK;` `[DebugAction("MyMod", "Do thing", allowedGameStates = AllowedGameStates.PlayingOnMap)] static void X()` (appears in the dev-mode debug actions menu) | — |

## Ticking

`Thing.Tick()` is `protected virtual`; things normally tick through
`TickInterval(int delta)` at a variable rate (1–15 ticks, `delta` = ticks elapsed). In comps
override `CompTickInterval(int delta)`; in hediff comps `CompPostTickInterval(ref float
severityAdjustment, int delta)`. Periodic work: `parent.IsHashIntervalTick(interval, delta)`.
Accumulators must add `delta`, not 1. `CompTick()/CompTickRare()/CompTickLong()` still exist
and follow the def's `tickerType` (Normal/Rare/Long/Never) — a comp only ticks if the thing's
`tickerType` ticks at all.

A faster engine doesn't make per-tick scans free: keep tick work bounded (cached sets updated on
spawn/despawn, work spread over ticks, no LINQ or allocations in hot paths) and measure it with
the frame profiler (`debugging.md`).

## Saving (Scribe)

In `ExposeData()` / `PostExposeData()`, every persistent field:

```csharp
Scribe_Values.Look(ref count, "count", 0);                         // primitives, enums, structs
Scribe_Defs.Look(ref def, "def");                                  // Def references
Scribe_References.Look(ref pawn, "pawn");                          // Things/Pawns saved elsewhere
Scribe_Deep.Look(ref data, "data");                                // IExposable owned by you
Scribe_Collections.Look(ref list, "list", LookMode.Reference);     // lists/dicts: pick LookMode
if (Scribe.mode == LoadSaveMode.PostLoadInit) list ??= new List<Pawn>();  // null after old saves
```
Keys are forever: renaming a key drops saved data. Saves move between 1.6 and 1.7 in both
directions, so keep the same keys and formats in both builds. Adding a mod mid-save is fine;
removing a mod with comps/components on saved things breaks references.

## Harmony

```csharp
new Harmony("yourname.mymod").PatchAll();   // in the Mod ctor; applies every [HarmonyPatch] class

[HarmonyPatch(typeof(Pawn_HealthTracker), nameof(Pawn_HealthTracker.AddHediff),
              new[] { typeof(Hediff), typeof(BodyPartRecord), typeof(DamageInfo?), typeof(DamageWorker.DamageResult) })]
static class Patch_AddHediff
{
    static bool Prefix(Hediff hediff, Pawn ___pawn) => !(hediff.def == MyDefOf.X && ___pawn.IsColonist);  // false = skip original (and later prefixes)
    static void Postfix(Pawn_HealthTracker __instance, Hediff hediff) { }
}
```

| Injection | Meaning |
|---|---|
| `__instance` | `this` (instance methods) |
| `__result` / `ref __result` | return value (postfix reads/changes; prefix sets it when returning false) |
| `__state` | value passed from this class's prefix to its postfix (any type; `out` in prefix) |
| `___field` / `ref ___field` | private field of the patched type (3 underscores) |
| `__args` | `object[]` of arguments |
| `__originalMethod`, `__runOriginal` | the MethodBase; whether the original will run / ran |
| parameter by name or `__0`, `__1` | original arguments (`ref` to modify) |

- Kinds: Prefix, Postfix (always runs, the safe default), Transpiler
  (`IEnumerable<CodeInstruction>`; use `CodeMatcher` and match semantically —
  `instruction.Calls(method)`, field loads — never local-slot numbers, offsets or instruction
  counts; verify the 1.7 IL with `decompile.py` + ILSpy), Finalizer (sees/replaces exceptions),
  Reverse patch (call a private original).
- Target overloads with the argument-types array (`AccessTools.Method(type, name, new[] {…})`,
  log and skip when it returns null rather than letting a null target cascade); properties with
  `MethodType.Getter/Setter`; constructors with `MethodType.Constructor`. Game
  (Assembly-CSharp) methods are never inlined on 1.7, so small ones are patchable; generic
  methods and methods in other assemblies may be — patch the caller. Abstract/interface methods
  have no body: patch the implementations.
- Ordering vs other mods: `[HarmonyPriority(Priority.High)]`, `[HarmonyBefore("id")]`,
  `[HarmonyAfter("id")]`. Prefixes returning false break other mods' prefixes — prefer postfixes.
- Failures appear as `HarmonyException` / `Patching exception in method …` in Player.log. With
  the Harmony mod, every stack trace lists the patches on its methods (`- POSTFIX <your id>:
  Type.Method <- …`), so use your packageId as the Harmony id. Its debug log is
  `links/logs/harmony.log.txt`.
- Conditional patches for optional mods: `[HarmonyPatch]` + `static bool Prepare() =>
  ModsConfig.IsActive("pkg.id")` and `static MethodBase TargetMethod() =>
  AccessTools.Method("Their.Type:Method")`.
- "It loads" doesn't prove a patch works: exercise every patched path in game.

## Threading

Game state (`Pawn`, `Map`, `Thing`, `DefDatabase`, jobs, UI) is main-thread-only, as in 1.6.
Background work may only compute on data you copied out; apply results on the main thread
(`LongEventHandler.ExecuteWhenFinished`, a `GameComponent` tick). The new runtime's timing can
expose or hide races that were dormant on 1.6.

## Useful APIs (verify signatures with decompile.py)

- Defs: `DefDatabase<T>.GetNamed(name, errorOnFail)`, `.GetNamedSilentFail`, `.AllDefs`.
- Mods: `ModsConfig.IsActive("pkg.id")`, `ModsConfig.BiotechActive` / `IdeologyActive` /
  `OdysseyActive` …, `ModLister.GetActiveModWithIdentifier`.
- Logging: `Log.Message/Warning/Error`, `Log.ErrorOnce(text, key)`; prefix with `[MyMod]`.
- Translation: `"MyMod_Key".Translate(arg1.Named("NAME"))`, keys in `Languages/English/Keyed`.
- Random/time: `Rand.Chance`, `Rand.Range`, `Find.TickManager.TicksGame`, `GenDate`,
  `GenTicks.TicksPerRealSecond`.
- Spawning: `ThingMaker.MakeThing(def, stuff)`, `GenSpawn.Spawn`, `GenPlace.TryPlaceThing`,
  `PawnGenerator.GeneratePawn(new PawnGenerationRequest(kind, faction))`.
- Health: `pawn.health.AddHediff(def, part)`, `HediffMaker.MakeHediff`,
  `pawn.health.hediffSet.GetFirstHediffOfDef`.
- UI: `Widgets`, `Listing_Standard`, `Text`, `GUI`/`Rect`, `Find.WindowStack.Add(...)`.
- Collections: on a net10 build `list.MaxBy(f)` / `MinBy` are `System.Linq`'s (null on an empty
  reference-type list); `GenCollection.MaxBy(list, f)` keeps Verse's throw-on-empty behaviour.
