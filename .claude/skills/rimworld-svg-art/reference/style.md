# The RimWorld look, measured

Numbers come from `analyze.py --summary` over the extracted vanilla textures of 1.6.4871
(Core + Biotech, ~1,000 sprites, 2026-09-25). p10–p90 ranges in brackets. Re-measure a category
before drawing for it — `vanilla_tex.py --extract '<regex>'`, then
`analyze.py '<cache>/png/<src>/<folder>/*.png' --summary`.

## Six rules that make it look like RimWorld

1. **Silhouette first.** At the starting camera zoom a 1-cell thing is ~30 screen px (1440p),
   at the far zoom ~12. What survives is the outline shape and one or two value blocks. Design
   the silhouette so the object is recognisable as a filled black shape; details are a bonus
   for the closest zoom (~65 px/cell).
2. **Black outline, weight fixed by cell size, not by texture size.** Things and icons have a
   pure-black (`#000`) outline ([analyze] `edge_ratio` 0.0 across items, weapons, animals):
   2–3 px per 64 px of cell for buildings and items, 3 px on 128 px weapons, 4 px on 128 px
   pawn parts (bodies, heads, hair, apparel), 4–5 px on 128 px UI icons. Round joins, even
   weight, anti-aliased. Inner lines (seams, panel edges) are thinner (1–2 px) and a darker
   shade of the local colour, not black.
3. **Plants are the exception.** No black line: the edge is a darker shade of the plant's own
   hue (edge/interior luminance 0.45–0.95, median 0.68; edge saturation = interior
   saturation), soft painterly mottling, low contrast (lum_range median 0.11).
4. **Anything tinted is drawn white.** The game multiplies the texture by a colour: stuff for
   made-from-material things (melee weapons, furniture, apparel), hair and skin colour for pawn
   parts, `graphicData/color` for animals. Measured interior luminance: apparel 0.95, bodies
   0.94, hair 0.97, furniture 0.63, melee weapons 0.87, all with saturation ≈ 0. So: draw it
   white-to-light-grey with grey shading, and put any fixed-colour part (steel bands, a gem)
   on a mask (`_m`, black channel) — otherwise it gets tinted too.
5. **Flat colour with soft, top-lit shading.** A base fill, a lighter upper plane, a darker lower
   plane or edge, occasionally a soft vertical gradient. Light comes from above (upper faces and
   top edges lighter). No cast shadows (the game draws them), no rim light, no specular
   hotspots beyond a small highlight, no hard dithering.
6. **Muted, earthy palette.** Metals near-neutral (saturation 0.01–0.05), woods orange-brown
   (`#a0643a`→`#6e3f22`), resources/drugs moderately saturated (0.25–0.35), mechanoids grey.
   Pure saturated colours are for UI command icons (red attack, blue arrows) — nowhere else.

## View and orientation

- **Map things are top-down with a hint of the front.** Buildings show their top face plus a
  short front face (≈ ⅕ of the depth) at the bottom of the image; the camera never rotates, so
  the front face stays at the bottom in `_north`, `_east`, `_south` — only the object's own
  features turn.
- **Items on the ground** are drawn flat, as if lying down, and the game rotates them randomly
  (`onGroundRandomRotateAngle` 35 on weapons): no fixed ground line.
- **Weapons point east:** muzzle / blade / head to the right, grip lower-left of centre.
  `equippedAngleOffset` in the def rotates them in hand.
- **Pawns and animals:** `_south` faces the viewer, `_east` is the side view facing right,
  `_north` the back. `_west` is optional (east mirrored).

## Per-category spec

| Category | Canvas (px) | Scale | Outline | Colour | Notes |
|---|---|---|---|---|---|
| Resource / stackable item | 64 | 64 px/cell | 3 px (2–3) | own | `Graphic_StackCount` `_a/_b/_c`: one piece → few → heap. Coverage 0.13–0.63 |
| Drug, medicine, small item | 64 | 64 px/cell | 2 px (1–3) | own | margin ~⅛ of canvas |
| Meal | 128 (some 512) | `Graphic_MealVariants` | ≈ 5 % of canvas (0.02–0.06) | own | dense, busiest shading of all items (lum_range 0.47) |
| Ranged weapon | 128 | drawSize 1 ≈ 128 px/cell | 3 px (3–4) | own, near-neutral | east-facing, coverage 0.10–0.33, low saturation except wooden stocks |
| Melee weapon | 128 | drawSize 1 | 3 px | **white** (stuff) | horizontal, blade/head right, handle dark grey |
| Furniture | 64 px per cell (bed 2×2 = 128) | `Graphic_Multi` | 2–3 px | **white/light grey** (stuff) | `CutoutComplex` + masks for fixed-colour parts; sheets/cushions = green (colorTwo) |
| Production building | 64 px per cell (3×1 bench → 224×96 at drawSize 3.5×1.5) | `Graphic_Multi` | 3 px | own, neutral greys | tools and props on the top face with a soft drop shadow, subtle grunge |
| Apparel (worn) | 128 | same canvas as the body | 4 px (3–6) | **white** | one file per body type `_Male/_Female/_Thin/_Hulk/_Fat` × `_north/_east/_south`; headgear without body type |
| Body | 128 | drawSize 1 | 4 px (5 hulk) | **white** | bbox male south ≈ (38,44)–(88,107) |
| Head / hair | 128 | own canvas | 4 / 3–4 px | **white** | head bbox ≈ (41,39)–(86,88); hair ≈ (38,35)–(90,78); the game offsets the head per body type |
| Animal | 128 (large: 256) | drawSize from def (cow 1.3) | 3 px (2–6) | **white/greyscale**, tinted by `color` | own colour only for markings that must not tint (use a mask or a second graphic) |
| Mechanoid | 128 | drawSize from def | 4 px | own, dark greys | high value contrast (lum_range 0.6) |
| Plant | 128 (small: 64) | drawSize from def | **none** — darker own hue, 2–3 px | own, saturation ~0.4 | stem base near bottom centre; soft noise mottling |
| Gene icon | 128 | UI | 5 px (4–5) | own; **white** for body-part genes | margin ~10 % (0.03–0.2), coverage ~0.3, 2–3 flat colours |
| Command / designator icon | 128 | UI, drawn at 75 px (`Gizmo.Height`) | 4 px (3.5–5) | bright, saturated allowed | fills the square (margin 0–10 %, coverage 0.4–0.45) |
| Small UI icon | 64 / 32 / 28 | UI | 0–4 px | often white on transparent | many are flat white glyphs tinted by code |

## What vanilla art does *not* have

- Thin hairline outlines, or outlines in a colour other than black (except plants and some
  effects).
- Photographic texture, strong gradients across the whole object, glossy highlights, bevel/emboss.
- Perspective: no vanishing points; parallel projection, front face as a flat strip.
- Drop shadows baked into things on the map (the game adds `shadowData` / contact shadow);
  props *on* a workbench do get a soft shadow on the bench top.
- Text in textures (it cannot be translated).

## When the reference is not vanilla

These rules describe Ludeon's art. A mod or texture pack the user picked wins where they
differ — e.g. Medieval Overhaul draws 128 px/cell with a 2.5-unit black outline and uses black
zigzag marks on straw; Gerrymon's Upscaled Vanilla Textures draws straw as layered tufts with no
marks. Measure the chosen set (`build_mod_refs.py`, `analyze.py --summary`) and record it in the
mod's `Art/STYLE.md`; mixing numbers from two references is the most common cause of a full
redo.

## Containers, piles and fill levels

Measured on vanilla shelves, hopper, MO open crates/barrels and ASF storage:

- **Open containers read by value, not lines**: a dark interior (MO: #949494 → #626262 before
  tint) under a light rim, a soft shadow band under the back rim, a slatted or planked front
  face one step darker than the top. (Vanilla shelves invert this — light interior, dark front
  band — only because items cover them; users judged the dark interior as "depth".)
- **Fill levels**: the pile covers the whole floor of the container at every level; a lower level
  shows more inner wall, a higher level less. Contents never rise above the rim or spill over.
  Full ≈ surface just below the rim.
- **Piles**: 3 passes — a dark bed filling the area, mid-tone pieces with random size, rotation
  and squash (not a grid, not one repeated shape), then ~25 % lighter pieces and small highlights
  on top. Darker and sparser at the back rim. Separate pieces with darker shades of the pile's
  own colour, not black outlines.
- **Related pieces share profile numbers**: gate posts = fence posts, end caps = body rim, a
  large variant = the small one scaled, not redrawn. Keep them as named constants in the
  generator.

## What users rejected (Barn Expanded, 2026-09)

Check a piece against this list before showing it:

- Hairline details: wood-grain lines, nails, tiny leg nubs — invisible in game, noisy up close.
- Inverted depth: light basin with dark rims, or no shadow inside an open container.
- Contents that fill from one side (side view) instead of the top-down "surface lowers" cue, and
  any overflow past the rim.
- Regular grids of identical pieces (a honeycomb of round pellets, bales in a perfect grid).
- One mark repeated as a stamp (the same zigzag/tick everywhere) — the eye finds the tiling.
- Black outlines on every small piece of contents — a black lattice at game zoom.
- Related pieces drawn at different heights or thicknesses (gate vs fence, cap vs body).
- Anything more saturated or cleaner than the reference set next to it.
