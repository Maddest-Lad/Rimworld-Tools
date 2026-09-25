# Texture pipeline facts (1.6.4871)

For folder layout, `graphicClass` → file naming, apparel body types and masks in defs, see
`../rimworld-mod-dev/reference/assets.md`. This file covers what matters when *making* the PNG.

## How the game loads a mod PNG

From `Verse.ModContentLoader.LoadTextureViaImageConversion` (decompiled, `decompile.py
ModContentLoader --full`):

1. `Texture2D.LoadImage` with a **full mipmap chain**.
2. If a side is < 4 or not a power of two (and texture compression is on — the default), the
   mip count is clamped (`StaticTextureAtlas.CalculateMaxMipmapsForDxtSupport`): it loads
   slower and **looks worse zoomed out**. Verbose log: "…reduced mipmap count…".
3. If both sides are multiples of 4, it is **DXT-compressed** (4×4 blocks: fine gradients band a
   little, edges of tiny details smear). Otherwise uncompressed (more VRAM).
4. `filterMode = Trilinear`, `anisoLevel = 2`.
5. A `.dds` next to the `.png` wins (pre-compressed, faster loads for big mods).

Consequences for the art:

- Use **power-of-two** canvases: 64, 128, 256, 512 (non-square allowed: 256×128). A 3×1
  building at 64 px/cell drawn with `drawSize (3.5,1.5)` is 224×96 in vanilla — legal
  (multiples of 4), but a new mod should prefer 256×128 with a matching `drawSize`.
- **Colour bleed**: transparent pixels' RGB is averaged into the smaller mips. Unbled
  transparent black makes a dark fringe (harmless on black-outlined art, visible on plants
  and glows); transparent white makes a light halo. `render.py` bleeds by default.
- Very thin features (≤ 1 px at texture size) vanish at the first mip; the camera spends most
  of its time at 12–30 px per cell.

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

- `Cutout` (default): texture × colour (stuff colour, `graphicData/color`, hair/skin colour).
  Draw tinted art white; the preview's `--tint` emulates this.
- `CutoutComplex` + mask: red channel → colour one (stuff / `colorOne`), green → colour two
  (`colorTwo`, e.g. bed sheets, ideology/style colours), black → texture's own colour. Vanilla
  furniture ships `_southm` etc. next to the textures (`vanilla_tex.py --search
  'furniture/bed/bed_.*m$'`). `render.py` applies a same-run mask in previews.
- Alpha: the `Cutout*` family is for opaque art with anti-aliased edges; for see-through
  content (mist, glass, glows) vanilla uses `Transparent`, `TransparentPlant`, `Mote*`
  shaderTypes (`def_lookup.py --xpath 'Defs/ThingDef[graphicData/shaderType="Transparent"]'`).
  Plants use `CutoutPlant` (wind sway). List: `def_lookup.py --grep . --type ShaderTypeDef`.

## Rendering pipeline used here

`render.py` → resvg (Rust, via `resvg-py`) → 8-bit RGBA PNG (straight alpha) → optional bleed.
resvg supports SVG 1.1 + most of SVG 2 static features (clip paths, masks, gradients, filters
including `feTurbulence`, `paint-order`), not scripting, animation or CSS beyond presentation
attributes and simple `<style>` rules. Fonts are system fonts — avoid text in textures anyway.
