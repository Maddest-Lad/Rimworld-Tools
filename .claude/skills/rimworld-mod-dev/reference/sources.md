# Sources (1.7 update researched 2026-10-12)

Ground truth, in priority order:

1. **The installed game** — 1.7.4976 rev1043 on Steam's `unstable` branch
   (`links/game/Version.txt`): Core + Royalty, Ideology, Biotech, Anomaly, Odyssey Defs under
   `links/game/Data/`, and `Assembly-CSharp.dll` decompiled with ilspycmd 11.0 into
   `.claude/skills/rimworld-mod-dev/.cache/decompiled/` (gitignored, reference only). Loader
   behaviour in `patching.md`, `mod-structure.md`, `xml-defs.md` and the scripts was read from
   `Verse.LoadedModManager`, `ModContentPack`, `ModLoadFolders`, `DirectXmlLoader`,
   `XmlInheritance`, `PatchOperation*`, `DefDatabase`, `ModMetaData`, `ModAssemblyHandler`,
   `ModContentLoader`, `Verse.Steam.Workshop`.
2. **The 1.6 → 1.7 diff** — member-level comparison of the decompiled 1.6.4871 and 1.7.4976
   `Assembly-CSharp.dll` (the basis of `v17-changes.md`), plus the 1.7 host and engine assemblies
   (`RimWorld.dll`, `Waylith*.dll`, `UnityStubs.dll`, `Brutal.Core.Logging.dll`) and
   `RimWorld.runtimeconfig.json` for the runtime switches, log format/location, command-line
   switches, texture compression, asset packs, shader loading and asset-bundle limits.
3. **Launch tests on 1.7.4976** (isolated `-savedatafolder`, `-QuitAfterBoot`): vanilla + all DLC
   boot; a net10 test mod (game DLL references, Lib.Harmony 3.0.0-rc.2) in `1.7/Assemblies` and a
   net472 test mod (Krafs.Rimworld.Ref 1.6.4871, Lib.Harmony 2.4.3) in `1.6/Assemblies` both
   loaded, ran `[StaticConstructorOnStartup]` and applied Harmony postfixes under Harmony 3; the
   resulting `Player.log` (exceptions, `[Ref]` ids, patch-owner lines) is what
   `/rimworld-log-debug` parses.
4. **Installed mods** (`links/workshop`) — the Harmony mod 3.0.0.0 (2009463077: `1.7/` = Harmony
   3.0.0-rc.2 for .NET 10, `1.6/` = 2.4.3; README: log location, stack-trace owners) and its
   decompiled `HarmonyMod.dll`; conventions (csproj settings, LoadFolders usage) from the other
   mods on disk.
5. **C# template build** — `templates/csharp` compiled with .NET SDK 10.0.201 against the 1.7.4976
   game assemblies and Lib.Harmony 3.0.0-rc.2.

Documentation:

- Ludeon, "Announcing the Waylith Engine and Update 1.7" (2026-10-12) —
  https://ludeon.com/blog/2026/10/announcing-the-waylith-engine-and-update-1-7/ : 2–4× performance,
  saves compatible both ways, mods expected to work unchanged, mark tested mods 1.7, modern C#,
  more accessible visual effects, PCs over ~10 years old may not run it.
- HarmonyRimWorld releases — https://github.com/pardeike/HarmonyRimWorld/releases (3.0.0.0:
  Harmony 3 for .NET 10 on 1.7, 2.4.3 on 1.6, patch owners in traces, log beside Player.log).
- Prepatcher — https://github.com/Zetrith/Prepatcher (its assembly reloader is specific to Unity's
  Mono runtime) and first-day r/RimWorld reports of 1.7 failures fixed by disabling it.
- A ChatGPT deep-research report on 1.7 (2026-10-12, user-supplied) — used for the risk framing
  (test first, transpilers/reflection/native/rendering as risk areas); every technical claim here
  was re-checked against the installed game.
- RimWorld Modding Wiki (wiki.gg) — dump `workspace/Rimworld Modding Wiki/rimworldmodding.wiki.gg-20260924-wikidump/`
  (~20 beginner pages written for 1.6: About File, Basic Concepts, Def Types, Melee Weapon Def,
  Mod Folder Basics/Versions, XML Basics/Inheritance/Software, Mod Usage). Its "ChatGPT" page is
  deliberately ignored (see `notes/decisions.md`); its valid point — models may know older game
  versions — is why every claim here is checked against the installed game.
- rimworldwiki.com Modding Tutorials — https://rimworldwiki.com/wiki/Modding_Tutorials :
  PatchOperations, MayRequire, Mod_Folder_Structure, About.xml, Textures, Localization,
  Testing_mods, Setting_up_a_solution (pre-1.7; several C# pages are outdated — prefer the
  decompiled source).
- Harmony docs — https://harmony.pardeike.net/articles/intro.html,
  https://harmony.pardeike.net/articles/patching-injections.html
- Community: RimWorld Discord #mod-development (Ludeon asks for 1.7 issue reports there).

Corrections made against the wiki while verifying: `chemicalNeed` is a HediffDef field (not
HediffStage); `hideAtSnowOrSandDepth` is a ThingDef field; `InteractionUtility` still exists
(social members moved to `SocialInteractionUtility`); a same-defName def in a later mod silently
replaces the earlier one (no error); `PatchOperationInsert` defaults to Prepend while `Add`
defaults to Append; `MayRequire` on a top-level `<Operation>` is ignored; the PawnsFinder members
are spelled `…Travelling…`.
