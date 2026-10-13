"""Regenerate the synthetic 1.7 fixtures (and, when a real log is available, a scrubbed excerpt).

The layout copies a real 1.7.4976 Player.log: a header block, then `<date> <time> <LEVEL>
[Category] message` entries, each followed by the logging call's captured stack.
"""

from __future__ import annotations

from pathlib import Path

FX = Path(__file__).resolve().parent / "fixtures"
REAL = Path(__file__).resolve().parents[5] / "links" / "logs" / "Player.log"
WS = r"C:\Program Files (x86)\Steam\steamapps\workshop\content\294100"


def header(pid: int = 1234) -> list[str]:
    return [
        "=== RimWorld by Ludeon Studios log ===",
        "Started:   2026-10-12 16:56:37.387 -07:00",
        "Version:   1.0.0.0",
        "OS:        Microsoft Windows 10.0.19044 (X64)",
        "Runtime:   .NET 10.0.10-waylithclr.dev",
        f"Process:   pid {pid}",
        r"Log file:  C:\Users\user\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Logs\Player.log",
        r'Command:   "C:\Games\RimWorld\RimWorld.dll" -quicktest',
        "",
    ]


def stack(*frames: str) -> list[str]:
    """The logging call's stack, as FileLog writes it under every entry."""
    return [f"    at {f} [0x0]" for f in frames]


def entry(level: str, category: str | None, message: str, *frames: str) -> list[str]:
    cat = f" [{category}]" if category else ""
    head = f"2026-10-12 16:56:38.757 {level:>5}{cat} {message}"
    log_call = {"ERROR": "Error", "WARN": "Warning"}.get(level, "Message")
    return [head] + stack(
        "Brutal.Logging.LogCategory.Info(LogString`1 message, String sourceMemberName)",
        f"Verse.Log.{log_call}(String text)",
        *(frames or ("Verse.PlayDataLoader.DoPlayLoad()",)),
    )


BOOT = entry(
    "INFO",
    "GraphicsDevice",
    "Selected GPU 'Test GPU' - best automatic match of 1 device(s).",
) + entry(
    "INFO",
    "Verse",
    "RimWorld 1.7.4976 rev1043",
    "RimWorld.VersionControl.LogVersionNumber()",
)
MODLIST = entry(
    "INFO",
    "Verse",
    "Initializing new game with mods:\n  - ludeon.rimworld\n  - brrainz.harmony\n  - example.buggymod",
    "Verse.Game.InitNewGame()",
)
TICK = entry(
    "ERROR",
    "Verse",
    "Exception ticking Pawn_Colonist_1 (at (10, 0, 12)): System.NullReferenceException: "
    "Object reference not set to an instance of an object.\n"
    "[Ref 1A2B3C4D]\n"
    r"   at BuggyMod.Comps.CompExplode.CompTickInterval(Int32 delta) in D:\src\CompExplode.cs:line 12"
    "\n   at Verse.ThingWithComps.TickInterval(Int32 delta)\n"
    "   at MonoMod.Utils.DynamicMethodDefinition.Verse.TickList.Tick_Patch1(TickList this)\n"
    "    - POSTFIX other.tickmod: Verse.TickList.Tick <- Void "
    "OtherMod.Patches.TickList_Tick:Postfix(TickList __instance)",
    "Verse.TickList.Tick()",
    "Verse.TickManager.DoSingleTick()",
)
XML_ERROR = entry(
    "ERROR",
    "Verse",
    "XML error: <hitFlags>IntendedTarget</hitFlags> doesn't correspond to any field in type "
    "VehicleTurretDef. Context: <Vehicles.VehicleTurretDef>...</Vehicles.VehicleTurretDef>\n"
    "\nPossible Matches:\n[Source: Titan Vehicles Upgrades]\n"
    f"[File: {WS}\\3484382302\\1.5\\Defs\\UpgradeTrees\\Tank.xml]",
    "Verse.DirectXmlToObject.GetFieldInfoForType(Type type, String token, XmlNode debugXmlNode)",
)
CATALOGUE = (
    XML_ERROR
    + entry(
        "ERROR",
        "Verse",
        "Could not resolve cross-reference to Verse.ThingDef named BasicBedBase (wanter=affected)\n"
        "\nPossible Matches:\n[Source: Core]\n"
        r"[File: C:\Games\RimWorld\Data\Core\Defs\Furniture.xml]",
        "Verse.DirectXmlCrossRefLoader.ResolveAllWantedCrossReferences(FailMode failReportMode)",
    )
    + entry("ERROR", "Verse", "Could not find a type named Vehicles.CompTurrets")
    + entry(
        "WARN",
        "Verse",
        "Mod Example dependency (other.mod) needs to have <downloadUrl> and/or "
        "<steamWorkshopUrl> specified.",
    )
    + entry(
        "ERROR",
        "Verse",
        "Created WorkshopItem for 3802032538 but there is no folder for it.",
    )
    + entry("WARN", "Verse", "Key binding conflict: A and B are both bound to Z.")
    + entry(
        "ERROR",
        "Verse",
        "Exception filling window for RimWorld.Dialog_Options: System.MissingMethodException: "
        "Method not found: 'Boolean Verse.Widgets.CheckboxLabeled(Rect, String)'.\n"
        "   at OldMod.Settings.DoWindowContents(Rect inRect)\n"
        "   at Verse.Window.InnerWindowOnGUI(Int32 x)",
    )
    + entry(
        "WARN",
        "UnityStubs",
        "QualitySettings.set_vSyncCount (QualitySettings.cs:88): Stub! You may not get expected "
        "results!",
        "UnityStubs.Internal.StubWarner.LogStub(String stubName, String filePath, Int32 lineNumber)",
        "FpsMod.Startup.ApplySettings()",
    )
    + entry(
        "WARN",
        "UnityDebug",
        "AssetBundle 'shinyshaders': shader 'Custom/Glow' can't be used: no Vulkan variant in "
        "this bundle and no adjacent Linux bundle beside it.",
    )
    + entry(
        "ERROR",
        "Verse",
        "Exception in Verse.StaticConstructorOnStartupUtility.CallAll: "
        "System.DllNotFoundException: Unable to load DLL 'fastnative' or one of its dependencies.\n"
        "   at NativeMod.Interop.Init()",
    )
    + entry(
        "WARN",
        "Vulkan",
        "VK_LAYER_KHRONOS_validation is not available; Vulkan validation messages are disabled for this run.",
    )
    + entry("INFO", "Verse", "Prepatcher: Starting... (vanilla load took 25.0s)")
    + entry("INFO", "Verse", "Prepatcher: Serializing patched assemblies")
    + entry(
        "INFO",
        "Verse",
        "[SomeMod] Harmony patches applied.",
        "SomeMod.Main..ctor(ModContentPack content)",
    )
)


def write(name: str, lines: list[str]) -> None:
    (FX / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    FX.mkdir(exist_ok=True)
    write("tick_spam.log", header() + BOOT + MODLIST + TICK * 5000)
    write("catalogue.log", header() + BOOT + MODLIST + CATALOGUE)
    second = entry("ERROR", "Verse", "Could not find a type named Vehicles.CompTurrets")
    write(
        "two_sessions.log",
        header(1) + BOOT + XML_ERROR + header(2) + second,
    )
    write(
        "unstamped_paste.log",
        [
            (
                "Exception ticking Pawn_Colonist_1: System.NullReferenceException: Object "
                "reference not set to an instance of an object."
            ),
            "   at BuggyMod.Comps.CompExplode.CompTickInterval(Int32 delta)",
            "   at Verse.ThingWithComps.TickInterval(Int32 delta)",
            "Some unrelated chatter",
        ],
    )

    if REAL.is_file():
        src = REAL.read_text(encoding="utf-8", errors="replace").splitlines()
        home = str(Path.home())
        scrubbed = [
            line.replace(home, r"C:\Users\user").replace(
                home.replace("\\", "/"), "C:/Users/user"
            )
            for line in src[:600]
        ]
        write("real_excerpt.log", scrubbed)


if __name__ == "__main__":
    main()
