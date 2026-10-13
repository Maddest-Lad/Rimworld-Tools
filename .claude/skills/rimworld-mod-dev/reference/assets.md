# Textures, sounds, shaders, translations

Verified against `Verse.ModContentLoader`, `Graphic_*`, `GraphicData`, `ShaderDef`,
`MaterialDef`, `ApparelGraphicRecordGetter`, `LoadedLanguage` and the vanilla shaders in
1.7.4976.

## Textures

- Formats: `.png` (normal), `.jpg/.jpeg`, `.psd`, `.dds` (a `.dds` with the same name wins).
  1.7 compresses every texture over 16 px to BC7 on load (GPU) and caches the result in
  `<save data>/TextureCache`; for Workshop releases the uploader's asset pack pre-bakes them
  (`mod-structure.md` → Asset packs), so hand-made DDS files are rarely worth it.
- Paths: `Textures/MyMod/Things/Item/Sword.png` is referenced as `MyMod/Things/Item/Sword` —
  no `Textures/`, no extension, forward slashes. Always put art under your own subfolder so paths
  never collide with vanilla or other mods (same path = one hides the other).
- Size: powers of two (64, 128, 256 …; non-square fine). Other sizes still load but get a
  clamped mip chain (blurrier/aliased zoomed out; verbose log "reduced mipmap count"). Vanilla
  items ≈ 64 px per cell, newer DLC/mods 128 px per cell. `graphicData/drawSize` (cells, e.g.
  `(2,2)`) sets on-map size independent of pixels.
- `graphicData/textureRepeats` (1.7): sample with wrap mode Repeat (scrolling/tiled effects);
  `graphicData/borderMipMaps` (1.7): keep a transparent border in every mip, for sprites whose
  edge must not bleed (beams, tiling strips).
- Style: items/buildings get a dark outline (~2 px per 64 px); plants usually a green one.

### graphicClass → files

| `graphicClass` | `texPath` points to | Files |
|---|---|---|
| `Graphic_Single` | a file | `Sword.png` (+ mask `Sword_m.png`) |
| `Graphic_Multi` | a file prefix | `Bed_north.png`, `Bed_east.png`, `Bed_south.png`, optional `Bed_west.png` (else east is mirrored); masks `Bed_northm.png` … (note: no underscore before `m`) |
| `Graphic_StackCount` | a **folder** | images sorted by name = stack sizes low → high (`Steel_a.png`, `Steel_b.png`, `Steel_c.png`) |
| `Graphic_Random` | a folder | one image picked per thing |
| `Graphic_Appearances` | a folder | per stuff appearance (`_Planks`, `_Bricks`, `_Smooth`) |
| `Graphic_Linked` / `Graphic_LinkedCornerFiller` | a file | atlas for walls/conduits (`linkType`, `linkFlags`) |
| `Graphic_Flicker`, `Graphic_Cluster`, `Graphic_Indexed`, `Graphic_Mote`… | see a vanilla user: `def_lookup.py --xpath 'Defs/ThingDef[graphicData/graphicClass="Graphic_Cluster"]'` | |

Masks: shader must support them (`shaderType` `CutoutComplex`); red channel = primary colour
(stuff/`colorOne`), green = secondary (`colorTwo`), black = uncoloured. On 1.7 the mask only
counts where the **mask's alpha > 0** (`MaskGate.glsl`; Waylith bleeds colour into transparent
texels), so export masks opaque.

### Apparel and pawns

- `apparel/wornGraphicPath` + `_<BodyType>_<dir>`: `Things/Pawn/Humanlike/Apparel/MyCoat/MyCoat`
  → `MyCoat_Male_south.png`, `MyCoat_Female_east.png`… for body types `Male`, `Female`, `Thin`,
  `Hulk`, `Fat` (Biotech: `Baby`, `Child` if children can wear it). Headgear/overhead, eye cover
  and packs use **no** body-type suffix: `MyHat_north.png` etc. Plus a ground texture via
  `graphicData`.
- Body/head/hair/beard/tattoo graphics come from their defs (`BodyTypeDef`, `HeadTypeDef`,
  `HairDef`…) with `_north/_east/_south`. Pawn rendering is the render-node tree
  (`PawnRenderTreeDef`, `PawnRenderNodeProperties` in genes/hediffs/apparel) — copy a vanilla
  gene or hediff that draws something (`def_lookup.py --uses renderNodeProperties`).
- Genes: `iconPath` (UI icon), graphics through `renderNodeProperties` or hair/skin/body fields.

## Sounds

- Formats: `.ogg` (preferred), `.wav`, `.mp3`, tracker `.xm/.it/.mod/.s3m`. Files under
  `Sounds/MyMod/...`, referenced by folder/file path without extension in a `SoundDef`:

```xml
<SoundDef>
  <defName>MyMod_Zap</defName>
  <context>MapOnly</context>
  <maxSimultaneous>2</maxSimultaneous>
  <subSounds>
    <li>
      <grains><li Class="AudioGrain_Folder"><clipFolderPath>MyMod/Zap</clipFolderPath></li></grains>
      <volumeRange>30~40</volumeRange>
      <pitchRange>0.9~1.1</pitchRange>
    </li>
  </subSounds>
</SoundDef>
```
`AudioGrain_Clip` + `clipPath` for a single file; `<forceToMono>true</forceToMono>` on a grain
(1.7) downmixes stereo files for positional sounds. Sustainers (looping, e.g. ambient) need
`<sustain>true</sustain>`; copy a vanilla one (`def_lookup.py --uses sustain --type SoundDef`).

## Shaders and materials (1.7)

Unity shaders are gone: the game draws with Vulkan, and shaders are GLSL 450 files declared in
XML. `shaderType` / `ShaderTypeDef.shaderPath` (`Map/Cutout`) resolve to the `ShaderDef` named
after the last path segment (`Cutout`); vanilla defs are in `Data/Core/Defs/ShaderDefs/`,
sources in `Data/Core/Shaders/Map|World/` and `Rendering/Shaders/`
(`def_lookup.py --grep . --type ShaderDef`).

```xml
<ShaderDef>
  <defName>MyMod_Shimmer</defName>
  <shaderProgram>
    <vertexShaderFileName>MapWorldUV.vert.glsl</vertexShaderFileName>   <!-- default SceneDefault.vert.glsl -->
    <fragmentShaderFileName>MyMod_Shimmer.frag.glsl</fragmentShaderFileName>
    <transparent>true</transparent>          <!-- also depthTest/depthWrite, cullMode, blendMode, stencil*, renderQueue -->
    <depthWrite>false</depthWrite>
    <renderQueue>3000</renderQueue>
    <textureWrapOverrides><li><key>_MainTex</key><value>Repeat</value></li></textureWrapOverrides>
  </shaderProgram>
</ShaderDef>
```

- GLSL files go in a load folder's `Shaders/` (e.g. `1.7/Shaders/MyMod_Shimmer.frag.glsl`);
  later mods' files with the same name override earlier ones, so prefix the names. Copy a
  vanilla shader as the starting point: uniforms live in `MaterialUniforms` (set 2, binding 0)
  with `// @color`, `// @default = …` annotations, textures are `sampler2D` at set 2, vertex
  inputs carry `// @vertex <Semantic> required|optional`; `#include "MaskGate.glsl"` etc. resolve
  against the shader folders.
- Reference it like a vanilla one: `<shaderType>MyMod_Shimmer</shaderType>` (needs a matching
  `ShaderTypeDef` with `shaderPath` ending in `MyMod_Shimmer`) or from a `MaterialDef`.
- `MaterialDef`: `shader`, `renderQueue`, and named `textures` (`name`, `path`, `offset`,
  `scale`, `alphaFromGrayscale`), `floats`, `colors`, `vectors`, `keywords` lists; get it in C# via
  `def.Material` / `CreateMaterialInstance()`. Vanilla: `Data/Core/Defs/MaterialDefs/`.
- Shader errors appear in `Player.log` as `Shader '<file>' …`; a name with no program logs
  "Shader def 'X' is not registered … using engine default". Dev launch option
  `-WatchShaders` hot-reloads shader files of mods in the local `Mods/` folder.
- Unity shaders in a mod's asset bundle only work if the bundle carries a Vulkan (SPIR-V)
  variant — port them instead.

## Languages

```
Languages/English/Keyed/MyMod_Keys.xml
Languages/English/DefInjected/ThingDef/MyMod_Weapons.xml
Languages/English/Strings/Names/MyMod_Names.txt
Languages/<Language (Native)>/...     e.g. "German (Deutsch)", "ChineseSimplified (简体中文)"
```

- **Keyed** (C# UI strings): `<LanguageData><MyMod_Hello>Hello {0}</MyMod_Hello></LanguageData>`;
  used as `"MyMod_Hello".Translate(name)` or with named args `{PAWN_nameDef}` +
  `pawn.Named("PAWN")`. Always prefix keys; missing keys show the raw key (garbled in dev mode).
- **DefInjected** (translate def text in *other* languages; English lives in the def itself):
  `<LanguageData><MyMod_Sword.label>épée</MyMod_Sword.label><MyMod_Sword.tools.head.label>tête</MyMod_Sword.tools.head.label></LanguageData>`
  — `defName.field.path`, list items by index or by their `label`/handle. Folder = def type.
- **Strings**: plain `.txt` word lists for name/grammar generation.
- Dev mode → debug actions → *Translation* tools can dump a translation report for a language.
