# Sources (researched 2026-09-24)

Ground truth, in priority order:

1. **The installed game** — 1.6.4871 rev590 (`links/game/Version.txt`): Core + Royalty, Ideology,
   Biotech, Anomaly, Odyssey Defs under `links/game/Data/`, and `Assembly-CSharp.dll` decompiled
   with ilspycmd 11.0 into `.claude/skills/rimworld-mod-dev/.cache/decompiled/` (gitignored,
   reference only). Loader behaviour in `patching.md`, `mod-structure.md`, `xml-defs.md` and the
   scripts was read from `Verse.LoadedModManager`, `ModContentPack`, `ModLoadFolders`,
   `DirectXmlLoader`, `XmlInheritance`, `PatchOperation*`, `DefDatabase`, `ModMetaData`.
2. **Installed mods** (`links/workshop`, 333 on disk) — conventions: csproj settings
   (net472/net48, Krafs.Rimworld.Ref 1.6.*, Lib.Harmony 2.3–2.4), LoadFolders usage, Harmony mod
   (2009463077) ships 0Harmony 2.4.1.
3. **C# template build** — `templates/csharp` compiled with .NET SDK 10 against
   Krafs.Rimworld.Ref 1.6.4871 and Lib.Harmony 2.4.1.

Documentation:

- RimWorld Modding Wiki (wiki.gg) — dump `workspace/Rimworld Modding Wiki/rimworldmodding.wiki.gg-20260924-wikidump/`
  (~20 beginner pages: About File, Basic Concepts, Def Types, Melee Weapon Def, Mod Folder
  Basics/Versions, XML Basics/Inheritance/Software, Mod Usage). Its "ChatGPT" page is
  deliberately ignored (see `notes/decisions.md`); its valid point — models may know older game
  versions — is why every claim here is checked against the installed game.
- rimworldwiki.com Modding Tutorials — https://rimworldwiki.com/wiki/Modding_Tutorials :
  RimWorld_1.6_Mod_Updates, PatchOperations, MayRequire, Mod_Folder_Structure, About.xml,
  Textures, Localization, Testing_mods, Setting_up_a_solution. Several C# pages there are marked
  outdated; prefer the decompiled source.
- Ludeon, "Announcing Odyssey and update 1.6" — https://ludeon.com/blog/2025/06/announcing-odyssey-and-update-1-6/
- Harmony 2 docs — https://harmony.pardeike.net/articles/intro.html,
  https://harmony.pardeike.net/articles/patching-injections.html
- Community: RimWorld Discord #mod-development; Ludeon's 1.6 Modder Primer (linked from the
  wiki's 1.6 page).

Corrections made against the wiki while verifying: `chemicalNeed` is a HediffDef field (not
HediffStage); `hideAtSnowOrSandDepth` is a ThingDef field; `InteractionUtility` still exists
(social members moved to `SocialInteractionUtility`); a same-defName def in a later mod silently
replaces the earlier one (no error); `PatchOperationInsert` defaults to Prepend while `Add`
defaults to Append; `MayRequire` on a top-level `<Operation>` is ignored.
