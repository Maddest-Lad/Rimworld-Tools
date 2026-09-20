"""Regenerate the synthetic fixtures (and, when a real log is available, a scrubbed excerpt)."""

from __future__ import annotations

from pathlib import Path

FX = Path(__file__).resolve().parent / "fixtures"
REAL = Path(__file__).resolve().parents[5] / "links" / "logs" / "Player.log"
WS = r"C:\Program Files (x86)\Steam\steamapps\workshop\content\294100"
HASH = "<abc123abc123abc123abc123abc123ab>:0 "

HEADER = [
    "Mono path[0] = 'C:/Games/RimWorld/RimWorldWin64_Data/Managed'",
    "Initialize engine version: 2022.3.35f1",
    "RimWorld 1.6.4871 rev590",
]
MODLIST = [
    "Initializing new game with mods:",
    "  - ludeon.rimworld",
    "  - brrainz.harmony",
    "  - example.buggymod",
]
TICK_MSG = (
    "Exception ticking Pawn_Colonist_1 (at (10, 0, 12)): System.NullReferenceException: "
    "Object reference not set to an instance of an object"
)
TICK_TRACE = [
    "  at BuggyMod.Comps.CompExplode.CompTick () [0x00012] in " + HASH,
    "  at Verse.ThingWithComps.Tick () [0x00020] in " + HASH,
    "  at (wrapper dynamic-method) Verse.TickList.Tick_Patch1(Verse.TickList)",
    "  at Verse.TickManager.DoSingleTick () [0x00090] in " + HASH,
]
CATALOGUE = [
    (
        "XML error: <hitFlags>IntendedTarget</hitFlags> doesn't correspond to any field in type "
        "VehicleTurretDef. Context: <Vehicles.VehicleTurretDef>...</Vehicles.VehicleTurretDef>"
    ),
    "",
    "Possible Matches:",
    "[Source: Titan Vehicles Upgrades]",
    f"[File: {WS}\\3484382302\\1.5\\Defs\\UpgradeTrees\\Tank.xml]",
    "Could not resolve cross-reference to Verse.ThingDef named BasicBedBase (wanter=affected)",
    "",
    "Possible Matches:",
    "[Source: Core]",
    r"[File: C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Data\Core\Defs\Furniture.xml]",
    "Could not find a type named Vehicles.CompTurrets",
    "Mod Example dependency (other.mod) needs to have <downloadUrl> and/or <steamWorkshopUrl> specified.",
    "Created WorkshopItem for 3802032538 but there is no folder for it.",
    "Key binding conflict: A and B are both bound to Z.",
    (
        "Exception filling window for RimWorld.Dialog_Options: System.MissingMethodException: "
        "Method not found: Verse.Widgets.CheckboxLabeled"
    ),
    "  at OldMod.Settings.DoWindowContents (UnityEngine.Rect inRect) [0x00000] in "
    + HASH,
    "Exception thrown from thread=2137.",
    "System.Threading.ThreadAbortException: Thread was being aborted.",
    "[Ref 54CF78B3]",
    "(wrapper managed-to-native) System.Threading.Monitor.Monitor_wait(object,int)",
    "  at System.Threading.Monitor.ObjWait (System.Boolean exitContext) [0x0002f] in "
    + HASH,
    "[SomeMod] Harmony patches applied.",
]


def write(name: str, lines: list[str]) -> None:
    (FX / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    FX.mkdir(exist_ok=True)

    tick = HEADER + MODLIST
    for i in range(5000):
        tick.append(TICK_MSG)
        tick.append(
            "[Ref 1A2B3C4D] Duplicate stacktrace, see ref for original"
            if i
            else "[Ref 1A2B3C4D]"
        )
        if i == 0:
            tick += TICK_TRACE
    write("tick_spam.log", tick)

    write(
        "fallback_noise.log",
        HEADER
        + [
            f"Fallback handler could not load library C:/Games/RimWorld/MonoBleedingEdge/data-{i:016X}.dll"
            for i in range(1000)
        ],
    )
    write("catalogue.log", HEADER + MODLIST + CATALOGUE)
    write(
        "two_sessions.log",
        HEADER + MODLIST + CATALOGUE[:5] + HEADER + MODLIST[:2] + [CATALOGUE[10]],
    )

    if REAL.is_file():
        src = REAL.read_text(encoding="utf-8", errors="replace").splitlines()
        excerpt = src[0:120] + src[370:410] + src[1230:1400]
        home = str(Path.home())
        scrubbed = [
            line.replace(home, r"C:\Users\user").replace(
                home.replace("\\", "/"), "C:/Users/user"
            )
            for line in excerpt
        ]
        write("real_excerpt.log", scrubbed)


if __name__ == "__main__":
    main()
