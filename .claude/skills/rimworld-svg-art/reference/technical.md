# Texture pipeline facts (1.7.4976)

For folder layout, `graphicClass` → file naming, apparel body types and masks in defs, see
`../rimworld-mod-dev/reference/assets.md`. This file covers what matters when *making* the PNG.

## How the game loads a mod PNG

From `Verse.ModContentLoader.LoadTextureViaImageConversion` and the Waylith texture runtime
(decompiled, `decompile.py ModContentLoader --full`):

1. `Texture2D.LoadFromFile` with a **full mipmap chain**; textures and sounds are prefetched in
   parallel while defs load.
2. If a side is < 4 or not a power of two (and texture compression is on — the default), the
   mip count is clamped (`StaticTextureAtlas.CalculateMaxMipmapsForDxtSupport`): it loads
   slower and **looks worse zoomed out**. Verbose log: "…reduced mipmap count…".
3. Every texture over 16 px is **BC7-compressed** on the GPU (4×4 blocks, but far less banding
   and edge smear than the old DXT; no multiple-of-4 rule). The result is cached in
   `<save data>/TextureCache`, so a second launch skips the work.
4. `filterMode = Trilinear`, `anisoLevel = 2`.
5. The engine bleeds colour into fully transparent texels to avoid cutout fringes.
6. A `.dds` next to the `.png` wins. Workshop releases built with the 1.7 uploader carry an
   `Assets.zip` per load folder with the same textures pre-baked (BC7, Kaiser-filtered mips) —
   the source PNG is still the thing you author.

Consequences for the art:

- Use **power-of-two** canvases: 64, 128, 256, 512 (non-square allowed: 256×128). A 3×1
  building at 64 px/cell drawn with `drawSize (3.5,1.5)` is 224×96 in vanilla — it loads, but
  with a clamped mip chain; a new mod should prefer 256×128 with a matching `drawSize`.
- Keep the **colour bleed** in your exports anyway (`render.py` does it by default): it fixes
  the mips of the PNG itself, and 1.6 players of a dual-version mod still need it. Unbled
  transparent black makes a dark fringe (harmless on black-outlined art, visible on plants
  and glows); transparent white makes a light halo.
- Very thin features (≤ 1 px at texture size) vanish at the first mip; the camera spends most
  of its time at 12–30 px per cell.
- Sprites whose edge must stay clean in every mip (beams, strips that tile) can set
  `graphicData/borderMipMaps`; scrolling/tiled effects `textureRepeats`.

## Resolution: pixels per cell

| Content | Vanilla density | Why |
|---|---|---|
| Buildings, furniture, floors | 64 px/cell | bed 128² at drawSize 2×2, bench 224×96 at 3.5×1.5 |
| Items, resources, drugs | 64 px on a 1-cell item | |
| Weapons, apparel, pawns, plants, icons | 128 px canvas | detail for the closest zoom and the UI |

Screen size of a cell = screen height ÷ (2 × camera orthographic size); size runs 11
(closest) → 60, starting at 24 (`CameraMapConfig.sizeRange`, `CameraDriver.StartingSize`):

| Screen | closest | starting | far |
|---|---|---|---|
| 1080p | 49 px/cell | 22 | 9 |
| 1440p | 65 | 30 | 12 |
| 2160p (4K) | 98 | 45 | 18 |

So 64 px/cell is 1:1 at the closest zoom on 1440p; 128 px/cell only pays off on 4K close-ups
or in the UI (inspect pane, info card). Double resolution costs 4× VRAM per texture — fine for
a few hero objects, wasteful for a 200-item mod. Command gizmos draw at 75 px
(`Gizmo.Height`), so 128 px icons are always downscaled.

## drawSize vs canvas

`graphicData/drawSize` (cells) is the size on the map regardless of pixels. Keep the same
**pixels per cell** as the category's vanilla neighbours (table above), otherwise the outline
weight and detail density look off next to them: at 64 px/cell a 3 px outline; at 128 px/cell
draw a 5–6 px outline (in cell units nothing changes — see `svg-craft.md`).

## Tint and masks (shader types)

1.7 draws with Vulkan; each `shaderType` is a GLSL program declared as a `ShaderDef`
(`links/game/Data/Core/Shaders/Map/<name>.frag.glsl` — readable, so the exact tint maths is one
file away).

- `Cutout` (default): texture × colour (stuff colour, `graphicData/color`, hair/skin colour),
  discarded below alpha 0.5. Draw tinted art white; the preview's `--tint` emulates this.
- `CutoutComplex` + mask: red channel → colour one (stuff / `colorOne`), green → colour two
  (`colorTwo`, e.g. bed sheets, ideology/style colours), black → texture's own colour. The mask
  only counts where **its alpha is > 0** (`MaskGate.glsl`), so export masks fully opaque.
  Vanilla furniture ships `_southm` etc. next to the textures (`vanilla_tex.py --search
  'furniture/bed/bed_.*m$'`). `render.py` applies a same-run mask in previews.
- Alpha: the `Cutout*` family is for opaque art with anti-aliased edges; for see-through
  content (mist, glass, glows) vanilla uses `Transparent`, `TransparentPlant`, `Mote*`
  shaderTypes (`def_lookup.py --xpath 'Defs/ThingDef[graphicData/shaderType="Transparent"]'`).
  Plants use `CutoutPlant` (wind sway). List: `def_lookup.py --grep . --type ShaderTypeDef`;
  programs: `--type ShaderDef`.

## Vanilla textures on disk

Core textures are in `links/game/Assets.zip` (`Resources/Textures/…`), DLC in
`links/game/Data/<DLC>/Assets.zip` (`Textures/…`): zstd-compressed BC7 DDS, the same art as 1.6
(opaque pixels within ~2–3 levels of the old extraction). `vanilla_tex.py` reads them; nothing
else in the install holds textures.

## Rendering pipeline used here

`render.py` → resvg (Rust, via `resvg-py`) → 8-bit RGBA PNG (straight alpha) → optional bleed.
resvg supports SVG 1.1 + most of SVG 2 static features (clip paths, masks, gradients, filters
including `feTurbulence`, `paint-order`), not scripting, animation or CSS beyond presentation
attributes and simple `<style>` rules. Fonts are system fonts — avoid text in textures anyway.
