# How the engine places textures (1.6.4871, from the decompiled code)

Draw to these rules and check with `compose.py` (it implements the linked atlas and accepts
any layout). Source: `rimworld-mod-dev/scripts/decompile.py <Type> --full`.

## Coordinates

- Map x → right, z → up (north). Images: y down. `_north` is the side facing up the screen.
- A thing's texture is drawn centred on its footprint, `drawSize` cells wide/high (not the
  footprint size: a 3×1 bench uses drawSize 3.5×1.5 so the art overhangs).
- **Horizontal rotations swap drawSize** (`Graphic.MeshAt`): for `_east`/`_west` of a
  non-drawRotated Graphic_Multi, drawSize (x, y) becomes (y, x). So a 2×1 thing's east
  texture should be drawn on a canvas with the long side vertical (e.g. 128×256 for 256×128
  south), or the art is squashed.
- `Graphic_Multi` fallbacks (`Graphic_Multi.Init`): no `_north` → uses `_south`;
  no `_east` → `_west` mirrored (or `_north`); no `_west` → `_east` mirrored. Vanilla doors
  and fence gates ship only `_south` + `_east`.

## Graphic_Linked atlas (fences, walls, conduits)

`MaterialAtlasPool` + `Graphic_Linked.LinkedDrawMatFrom`:

- The texture is a **4×4 grid** of sub-tiles. Index = N·1 + E·2 + S·4 + W·8 (which of the 4
  neighbours it links to, `GenAdj.CardinalDirections` order N, E, S, W).
- Sub-tile column = index % 4; row = index // 4 **counted from the bottom** of the image.
- Only the **central 0.1875 of each 0.25 tile** is shown (UV offset 1/32): a 1/8-tile border
  around every sub-tile is never visible. On a 640 px atlas: 160 px tiles, 120 px drawn, 20 px
  border. The drawn part covers exactly one cell.
- So anything meant to sit on a cell boundary (a post shared by two cells) must be drawn as two
  halves at the edges of the two neighbouring sub-tiles' visible areas.
- `linkType Asymmetric` (vanilla fences): same atlas; additionally links to cells with
  `asymmetricLink.linkFlags` and to doors (`linkToDoors`), and can draw door border pieces.
  In `compose.py`, pass the gate cell as `links_to`.

## Doors (`Building_Door`, `Building_MultiTileDoor`, `Building_SupportedDoor`)

- The **mover** texture is one door leaf. `DrawMovers` draws it twice, once with
  `plane10Flip` (mirrored), offset in opposite directions along the door's axis. Closed, the two
  copies overlap exactly, so the texture is **one leaf on the left half** (hinge at the left
  edge, a hair past the centre line): vanilla `DoorSimple_Mover`, `FenceGate_Mover_south` are
  64 px with the leaf at x 0–34; the mirrored copy supplies the right leaf.
- 1×1 door: offset = 0.45 × OpenPct cells, scale 1.
- Multi-tile door (e.g. 2×1 ornate/barn door): `MoverDrawScale` (0.5, 1): each leaf covers half
  the width; offset = 0.25 + 0.35 × OpenPct. An optional `upperMoverGraphic` moves faster
  (OpenPct × 2.5).
- `Building_SupportedDoor` (also usable for 1×1 gates): `doorSupportGraphic` at
  BuildingOnTop altitude (posts/frame beside the leaves), `doorTopGraphic` at Blueprint altitude
  (header beam drawn **above pawns**). Both with their `…Offset` fields.
- So the leaf art differs by door size: a **1-cell** door's two copies overlap on one cell, so its
  texture holds one leaf on the left half; a **multi-cell** door's copies sit side by side
  (closed: centres at ±0.25 × width), so each mover texture is a whole leaf filling its canvas.
- East-facing doors: the leaf quad is rotated with the door (90° clockwise), and the mirrored
  copy is mirrored along the door axis.
- Preview: `compose.py` `door` layer (both leaves, `open` 0..1, support, top).

## Storage with contents (Adaptive Storage Framework and similar)

- Body texture tinted by stuff; fill layers listed in `graphicDatas` with
  `colorOneSource None` keep their own colour, drawn above the body (`BuildingOnTop`).
- Fill art sits **inside** the body's rim: no outline of its own (lint: allow `outline`), and it
  must never extend past the rim — the lower the level, the more inner wall shows.
- Front-layer textures (`…Layer`, e.g. MO Adaptive Storage) draw the container's front edge
  again above the contents, so items look inside.

## Stack counts, random, meals

- `Graphic_StackCount`: folder; files sorted by name = small → large stacks (`_a`, `_b`, `_c`).
- `Graphic_Random`: folder; one picked per thing (seeded by thing id).
- `Graphic_MealVariants` (meals): folder per meal with variants.

## Terrain

- Terrain textures tile in world space; vanilla surfaces are 1024 px and repeat every 16
  cells = **64 px per cell** (sterile tile: 16×16 tiles in 1024 px, one tile per cell).
  Their UVs come from the shader, not C#. Draw floor textures seamlessly periodic at 1024 px
  (`feTurbulence stitchTiles="stitch"` + copies of edge-crossing shapes at ±1024).
- Terrain is tinted by `TerrainDef.color` (concrete 140 grey) or stuff for floors made of it.

## Altitudes (draw order)

Floor/terrain < filth < buildings (`Building`) < items < `BuildingOnTop` (fills, door supports)
< pawns < `Blueprint`-level overlays (door tops). Things that must appear above pawns belong in
a separate top texture, not in the body.
