# Mod folder, About.xml, LoadFolders

Verified against `Verse.ModMetaData`, `ModContentPack.InitLoadFolders`, `ModLoadFolders`,
`DirectXmlLoader`, `Verse.Steam.Workshop` and Waylith's `ContentPacks` in 1.7.4976.

## Layout

```
MyMod/
  About/About.xml          required, exactly one, only at the root
  About/Preview.png        Workshop/mod-list image; 640×360 (16:9), must stay < 1 MB
  About/ModIcon.png        optional small icon (auto-loaded; or <modIconPath> to a texture)
  About/PublishedFileId.txt  written by the in-game uploader; keep it once published
  LoadFolders.xml          optional; root only
  1.7/                     version folder: Defs/, Patches/, Assemblies/ for 1.7
    Assemblies/ Defs/ Patches/
  1.6/                     only if the mod also supports 1.6 (1.7 ignores it while 1.7/ exists)
  Common/                  loaded for every version (Textures/, Sounds/, Languages/, Shaders/, shared Defs)
  Defs/ Patches/ Textures/ Sounds/ Languages/ Shaders/   root: also always loaded
  Source/                  C# project (not loaded; exclude from uploads if you like)
  <load folder>/Assets.zip (+ .stamps)   asset pack written by the 1.7 uploader (see Publishing)
```

Folder names are exact (`Defs`, `Patches`, `Assemblies`, `Textures`, `Sounds`, `Languages`,
`Shaders` — GLSL files for `ShaderDef`s, `assets.md`).
Inside `Defs/` and `Patches/` subfolders and file names are free, but avoid spaces/special
characters; files starting with `.` are ignored.

## Which folders load (no LoadFolders.xml)

Descending priority: `1.7/` (exact major.minor) — or, if absent, the newest version folder not
newer than the game (else the oldest; so a `1.6/`-only mod loads `1.6/` on 1.7) — then
`Common/`, then the mod root. For each content type the **first file per relative path wins**:
`1.7/Defs/Weapons.xml` hides `Defs/Weapons.xml` and `Common/Defs/Weapons.xml`. Different file
names all load. Files are read in ordinal path order.

## LoadFolders.xml

Used instead of the default list whenever it defines any version. The game picks `v1.7` (or the
newest defined version ≤ 1.7, else `<default>`). **Later `li` = higher priority.**

```xml
<loadFolders>
  <v1.7>
    <li>/</li>                                   <!-- root; "/" or "\" -->
    <li>1.7</li>
    <li IfModActive="Ludeon.RimWorld.Biotech">Mods/Biotech</li>          <!-- any of (comma list) -->
    <li IfModActiveAll="vanillaexpanded.vfecore,oskarpotocki.vfe.empire">Mods/VFE</li>
    <li IfModNotActive="ceteam.combatextended">Mods/NoCE</li>
  </v1.7>
</loadFolders>
```

To keep 1.6 support, add a `<v1.6>` block listing the 1.6 folders (e.g. `1.6` for a net472
assembly, shared folders for everything else).

packageIds in conditions ignore case and a `_steam` suffix. This is the cleanest way to ship
optional compatibility patches: one folder per target mod, loaded only when it is active — its
patches then need no FindMod guard.

## About.xml (ModMetaData)

```xml
<?xml version="1.0" encoding="utf-8"?>
<ModMetaData>
  <name>My Mod</name>
  <packageId>yourname.mymod</packageId>
  <author>yourname</author>                       <!-- or <authors><li>…</li></authors> -->
  <modVersion IgnoreIfNoMatchingField="True">1.0.0</modVersion>
  <url>https://github.com/you/mymod</url>
  <supportedVersions><li>1.6</li><li>1.7</li></supportedVersions>   <!-- only versions you tested -->
  <description>What it does. Plain text, shown in the mod list.</description>
  <modDependencies>
    <li>
      <packageId>brrainz.harmony</packageId>
      <displayName>Harmony</displayName>
      <steamWorkshopUrl>steam://url/CommunityFilePage/2009463077</steamWorkshopUrl>
      <downloadUrl>https://github.com/pardeike/HarmonyRimWorld/releases/latest</downloadUrl>
    </li>
  </modDependencies>
  <loadAfter><li>brrainz.harmony</li><li>Ludeon.RimWorld.Biotech</li></loadAfter>
  <loadBefore><li>some.othermod</li></loadBefore>
  <incompatibleWith><li>some.conflictingmod</li></incompatibleWith>
</ModMetaData>
```

| Field | Rule |
|---|---|
| `packageId` | Required, globally unique. Regex from the game: 1–60 chars, **letters, digits and dots only**, at least one dot, no leading dot, no `..`, ends alphanumeric. `yourname.mymod` ✔ `your_name.my-mod` ✘. Case-insensitive; the game appends `_steam` to Workshop copies internally. Never change it after release (saves/settings/dependencies key on it). |
| `name` | Shown to players; `PatchOperationFindMod` matches it. Keep it stable. |
| `supportedVersions` | `<li>1.7</li>` (plus `1.6` if tested there). Missing = warning; without the running version the mod list shows it yellow ("not made for this version") — on 1.7 a 1.6-only mod still loads. Add 1.7 only after testing. |
| `modDependencies` | `packageId`, `displayName`, `steamWorkshopUrl` and/or `downloadUrl` (without a URL the game logs a warning). `<alternativePackageIds><li>…</li></alternativePackageIds>` accepts forks (e.g. a Lite variant). DLCs: `Ludeon.RimWorld.<Royalty\|Ideology\|Biotech\|Anomaly\|Odyssey>`. Harmony mods depend on `brrainz.harmony`, never on `zetrith.prepatcher` (broken on 1.7). |
| `loadAfter` / `loadBefore` | Soft ordering hints for the sorter/mod manager. Put every mod you patch or inherit from in `loadAfter`. |
| `forceLoadAfter` / `forceLoadBefore` | Hard: the game refuses/complains when violated. Rarely appropriate. |
| `incompatibleWith` | Warns in the mod list. |
| `…ByVersion` | `modDependenciesByVersion`, `loadAfterByVersion`, `loadBeforeByVersion`, `incompatibleWithByVersion`, `descriptionsByVersion`: children `<v1.7>…</v1.7>`. |
| `modIconPath` | Texture path (under `Textures/`) for the icon; else `About/ModIcon.png`. |
| `modVersion` | Free string; add `IgnoreIfNoMatchingField="True"` so pre-1.4 games don't error. |
| `shortName`, `steamAppId` | Rare. |

Official content: `Ludeon.RimWorld` (Core), `Ludeon.RimWorld.Royalty`, `.Ideology`, `.Biotech`,
`.Anomaly`, `.Odyssey`. Their mod *names* (for FindMod) are `Core`, `Royalty`, `Ideology`,
`Biotech`, `Anomaly`, `Odyssey`.

## Load order effects

- All mods' `Defs` are merged into one document in load order, then **all** mods' patches run in
  load order, then inheritance resolves, then defs are built. So a patch sees every mod's defs
  (regardless of order) but only the *patched* state left by earlier mods' patches.
- A `Name` parent is looked up in your own mod first, then the nearest earlier mod; a parent
  from a later-loading mod is invisible → `Could not find parent node named …`.
- Same `defName` + def type in two mods: the later-loading mod's def **silently replaces** the
  whole earlier def (no merge, no error; `DefDatabase.AddAllInMods`). Other mods' patches then hit
  your copy, and anything the original gained later is lost — patch the original instead. Twice
  in one mod: `Mod X has multiple ThingDefs named Y. Skipping.`

## Deploying and publishing

- Local deploy: copy `workspace/<Mod>` → `links/mods/<Mod>` (the game's `Mods/` folder), e.g.
  `robocopy workspace\MyMod links\mods\MyMod /MIR /XD Source obj .git .vs` (PowerShell/cmd).
  Restart the game to reload defs (dev-mode hot reload is partial). A startup check without
  clicking: `-QuitAfterBoot` (`debugging.md`).
- Publishing: **dev mode on** (the button only shows then) → Mods menu → select the local mod →
  *Upload to Steam Workshop*. RimWorld writes `About/PublishedFileId.txt`; keep it for updates.
  The whole folder uploads — remove `Source/obj`, `.git`, test files first.

### Asset packs (1.7 uploader)

The upload dialog offers **Build asset pack** (on by default): for every load folder with
`Textures/` or `Sounds/` (version folders ≥ 1.7 plus the newest older one, `Common/`, root) it
bakes `<load folder>/Assets.zip` — textures as mipmapped BC7 DDS (Kaiser filter; `borderMipMaps`
textures keep a clear border), sounds as-is, zstd — then uploads a staged copy from
`%TEMP%\RimWorldWorkshopUpload\<packageId>`. 1.7 mounts the pack over the load folder, which
speeds up downloads and loading.

- The pack is written into the mod folder you upload from, with a local `Assets.zip.stamps`
  sidecar (not uploaded). A source file whose size/date differs from its stamp overrides the
  baked copy, so editing PNGs after an upload is safe locally.
- **Don't upload source textures** drops the PNG/PSD/sound files that went into a pack: smaller
  upload, but 1.6 can't read `Assets.zip` — leave it unticked while you support 1.6.
- Offline bake (CI, checking sizes): `RimWorld.exe -BakeModAssetPacks="<mod root>;<mod root>"`
  bakes and exits instead of starting the game (errors in `Player.log`).
