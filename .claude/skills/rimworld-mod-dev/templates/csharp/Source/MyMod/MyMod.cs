using HarmonyLib;
using LudeonTK;
using RimWorld;
using UnityEngine;
using Verse;

namespace MyMod
{
    // Instantiated once at startup (before defs load) for every mod assembly that defines a Mod subclass.
    public class MyModMod : Mod
    {
        public static MyModSettings Settings;

        public MyModMod(ModContentPack content) : base(content)
        {
            Settings = GetSettings<MyModSettings>();
            new Harmony("yourname.mymod").PatchAll();
        }

        public override string SettingsCategory() => "My Mod";

        public override void DoSettingsWindowContents(Rect inRect)
        {
            var list = new Listing_Standard();
            list.Begin(inRect);
            list.CheckboxLabeled("Enable glow", ref Settings.enableGlow);
            list.Label($"Radius: {Settings.radius:F1}");
            Settings.radius = list.Slider(Settings.radius, 1f, 20f);
            list.End();
        }
    }

    public class MyModSettings : ModSettings
    {
        public bool enableGlow = true;
        public float radius = 5f;

        public override void ExposeData()
        {
            Scribe_Values.Look(ref enableGlow, "enableGlow", true);
            Scribe_Values.Look(ref radius, "radius", 5f);
        }
    }

    // Runs after all defs are loaded and cross-references resolved.
    [StaticConstructorOnStartup]
    public static class MyModStartup
    {
        static MyModStartup()
        {
            Log.Message($"[MyMod] {DefDatabase<ThingDef>.AllDefsListForReading.Count} ThingDefs loaded");
        }
    }

    [DefOf]
    public static class MyModDefOf
    {
        public static ThingDef Steel;

        static MyModDefOf() => DefOfHelper.EnsureInitializedInCtor(typeof(MyModDefOf));
    }

    // XML: <comps><li Class="MyMod.CompProperties_Pulse"><intervalTicks>250</intervalTicks></li></comps>
    public class CompProperties_Pulse : CompProperties
    {
        public int intervalTicks = 250;

        public CompProperties_Pulse() => compClass = typeof(CompPulse);
    }

    public class CompPulse : ThingComp
    {
        private int pulses;

        public CompProperties_Pulse Props => (CompProperties_Pulse)props;

        // 1.6: things tick in intervals; delta is how many ticks this call covers.
        public override void CompTickInterval(int delta)
        {
            if (parent.IsHashIntervalTick(Props.intervalTicks, delta))
                pulses++;
        }

        public override void PostExposeData() => Scribe_Values.Look(ref pulses, "pulses", 0);

        public override string CompInspectStringExtra() => $"Pulses: {pulses}";
    }

    // Postfix: +10% market value for anything with CompPulse.
    [HarmonyPatch(typeof(StatWorker), nameof(StatWorker.GetValueUnfinalized))]
    public static class Patch_StatWorker_GetValueUnfinalized
    {
        public static void Postfix(StatRequest req, ref float __result, StatDef ___stat)
        {
            if (___stat == StatDefOf.MarketValue && req.Thing is ThingWithComps t && t.GetComp<CompPulse>() != null)
                __result *= 1.1f;
        }
    }

    // Prefix: returning false skips the original (and lower-priority prefixes) - use sparingly.
    [HarmonyPatch(typeof(Pawn_HealthTracker), nameof(Pawn_HealthTracker.AddHediff),
        new[] { typeof(Hediff), typeof(BodyPartRecord), typeof(DamageInfo?), typeof(DamageWorker.DamageResult) })]
    public static class Patch_Pawn_HealthTracker_AddHediff
    {
        public static bool Prefix(Hediff hediff, Pawn ___pawn)
        {
            return !(MyModMod.Settings.enableGlow && hediff.def == HediffDefOf.Malnutrition && ___pawn.IsColonist);
        }
    }

    public static class MyModDebugActions
    {
        [DebugAction("MyMod", "Log pulse comps", allowedGameStates = AllowedGameStates.PlayingOnMap)]
        private static void LogPulseComps()
        {
            foreach (Thing t in Find.CurrentMap.listerThings.AllThings)
                if (t is ThingWithComps twc && twc.GetComp<CompPulse>() != null)
                    Log.Message($"[MyMod] {t} at {t.Position}");
        }
    }

    // Per-save state; saved with the game.
    public class MyModGameComponent : GameComponent
    {
        public int daysSeen;

        public MyModGameComponent(Game game) { }

        public override void GameComponentTick()
        {
            if (Find.TickManager.TicksGame % GenDate.TicksPerDay == 0)
                daysSeen++;
        }

        public override void ExposeData() => Scribe_Values.Look(ref daysSeen, "daysSeen", 0);
    }

    // Attach with <modExtensions><li Class="MyMod.MyExtension"><bonus>2</bonus></li></modExtensions>
    public class MyExtension : DefModExtension
    {
        public float bonus = 1f;
    }
}
