# C# for RimWorld 1.6

Everything here compiles: `templates/csharp/Source/MyMod` was built against Krafs.Rimworld.Ref
1.6.4871 + Lib.Harmony 2.4.1 with .NET SDK 9/10 (`dotnet build -c Release`), and every API it
uses was checked in the decompiled game. Before overriding or patching anything, read the real
signature: `python .claude/skills/rimworld-mod-dev/scripts/decompile.py <Type> [--grep …]`.

## Project

`templates/csharp/Source/MyMod/MyMod.csproj` (SDK-style):

- `TargetFramework` **net472** (what nearly all 1.6 mods use; the game runs Unity's Mono with a
  4.x profile). `LangVersion latest` is fine — only newer *runtime* APIs are unavailable.
- `Krafs.Rimworld.Ref` `1.6.*` — publicized reference assemblies of the game + Unity; nothing of
  it is copied to output. Pin (`1.6.4871`) to match a specific game build.
- `Lib.Harmony` with `ExcludeAssets="runtime"` — compile against it, **never ship
  `0Harmony.dll`**; the Harmony mod (`brrainz.harmony`, Workshop 2009463077, currently 0Harmony
  2.4.1) provides it. Don't compile against a newer Lib.Harmony than that if you use new APIs.
- Output `..\..\1.6\Assemblies\` with `AppendTargetFrameworkToOutputPath=false`: the DLL lands in
  `<Mod>/1.6/Assemblies/`. Don't copy UnityEngine/Assembly-CSharp into Assemblies.
- Referencing another mod's DLL: `<Reference Include="X"><HintPath>…\links\workshop\<pfid>\1.6\Assemblies\X.dll</HintPath><Private>false</Private></Reference>`
  and add that mod to `modDependencies` + `loadAfter`. For an *optional* mod, avoid hard
  references (reflection, or a separate assembly in a LoadFolders `IfModActive` folder).

Build: `dotnet build workspace/<Mod>/Source/<Proj> -c Release`. The game locks loaded DLLs —
close it before rebuilding/deploying.

## Startup order (what exists when)

1. `Mod` subclasses are constructed (**`LoadedModManager.CreateModClasses`**) — before any XML is
   loaded. Do: `GetSettings<T>()`, `new Harmony(id).PatchAll()`. Don't touch defs.
2. Defs XML merged → patches → inheritance → defs built → cross-references resolved →
   `[DefOf]` classes bound.
3. `[StaticConstructorOnStartup]` static constructors run (main thread, all defs ready,
   textures loadable). Use for `ContentFinder<Texture2D>.Get(...)` into `static readonly`
   fields, def post-processing, caches.

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
| Right-click menu (1.6) | subclass `FloatMenuOptionProvider` (auto-discovered) | — |
| New job | `JobDriver` (`MakeNewToils`, `TryMakePreToilReservations`) + `JobDef` (`driverClass`) + `WorkGiver_Scanner` + `WorkGiverDef` | JobDef/WorkGiverDef |
| Custom thing class | `class MyBuilding : Building` | `<thingClass>MyMod.MyBuilding</thingClass>` |
| Gizmos | override `GetGizmos()` / `CompGetGizmosExtra()`; `Command_Action`, `Command_Toggle` | — |
| Debug actions | `using LudeonTK;` `[DebugAction("MyMod", "Do thing", allowedGameStates = AllowedGameStates.PlayingOnMap)] static void X()` (appears in the dev-mode debug actions menu) | — |

## Ticking in 1.6

`Thing.Tick()` is `protected virtual`; things normally tick through
`TickInterval(int delta)` at a variable rate (1–15 ticks, `delta` = ticks elapsed). In comps
override `CompTickInterval(int delta)`; in hediff comps `CompPostTickInterval(ref float
severityAdjustment, int delta)`. Periodic work: `parent.IsHashIntervalTick(interval, delta)`.
Accumulators must add `delta`, not 1. `CompTick()/CompTickRare()/CompTickLong()` still exist
and follow the def's `tickerType` (Normal/Rare/Long/Never) — a comp only ticks if the thing's
`tickerType` ticks at all.

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
Keys are forever: renaming a key drops saved data. Adding a mod mid-save is fine; removing a
mod with comps/components on saved things breaks references.

## Harmony (2.x)

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
  (`IEnumerable<CodeInstruction>`; use `CodeMatcher`; brittle across updates — verify IL with
  `decompile.py` + ILSpy), Finalizer (sees/replaces exceptions), Reverse patch (call a private
  original).
- Target overloads with the argument-types array; properties with `MethodType.Getter/Setter`;
  constructors with `MethodType.Constructor`. Generic and very small methods may be inlined by
  Mono — patch the caller instead. Abstract/interface methods have no body: patch the
  implementations.
- Ordering vs other mods: `[HarmonyPriority(Priority.High)]`, `[HarmonyBefore("id")]`,
  `[HarmonyAfter("id")]`. Prefixes returning false break other mods' prefixes — prefer postfixes.
- Failures appear as `HarmonyException` / `Patching exception in method …` in Player.log, naming
  the patch class.
- Conditional patches for optional mods: `[HarmonyPatch]` + `static bool Prepare() =>
  ModsConfig.IsActive("pkg.id")` and `static MethodBase TargetMethod() =>
  AccessTools.Method("Their.Type:Method")`.

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
