# Writing the SVG by hand

Everything here renders identically in `render.py` (resvg). Every template in `templates/`
follows this structure; copy the closest one.

## File skeleton

```xml
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="64" height="64" viewBox="0 0 64 64">
  <!-- what, graphicClass, canvas, tinted or own colour, outline weight -->
  <defs> parts as <path id>, their clipPaths, gradients, filters </defs>
  <!-- 1 outline underlay -->  <!-- 2 fills -->  <!-- 3 shading -->  <!-- 4 inner lines -->
</svg>
```

- **Work in cell units.** For map things make the viewBox one cell = 64 units (a 2×1 bench:
  `0 0 128 64`), then choose the pixel size at render time (`--size`). The outline weight
  in units then matches vanilla at any resolution (2.5–3 units per cell). For weapons and UI
  icons use a 128-unit viewBox (their conventions are per 128 px canvas).
- `width`/`height` = the default output size in px. `--size` overrides it; keep it a power of
  two (see `technical.md`).
- Keep ≥ 3 units of transparent margin so the outline and its anti-aliasing are not clipped
  (`render.py` warns when alpha touches the canvas edge).
- **No `--` inside `<!-- comments -->`** — it is invalid XML and resvg refuses the file. Write
  "tint option", not the flag.
- Use `xlink:href` together with the `xmlns:xlink` declaration (plain `href` also works in
  resvg, `xlink:href` keeps other editors happy).

## Layer 1 — the outline underlay

Define every part once in `<defs>`, then stroke *all* of them in black beneath the fills:

```xml
<g fill="#000" stroke="#000" stroke-width="6" stroke-linejoin="round">
  <use xlink:href="#blade"/><use xlink:href="#grip"/><use xlink:href="#guard"/>
</g>
<use xlink:href="#blade" fill="url(#metal)"/>  <!-- fills on top hide the inner half -->
```

- Visible outline = stroke-width ÷ 2 (the inner half is covered by the fill). 6 → 3 px.
- Because parts are unioned before the fills go on, touching parts share one continuous
  silhouette and no black line appears between them — seams are drawn in layer 4 instead.
- For a thin stroke-only part (a stem, a strap, a wire) draw the black stroke wider:
  `stroke-width = part width + 2 × outline`, then the coloured stroke on top.
- Overlapping *separate objects* (stack pieces, leaves) each get their own underlay, drawn
  back to front, so each reads as its own shape (see `resource_b.svg`).
- `stroke-linejoin="round"` always — mitred corners spike out on sharp points.
- Do not use `paint-order="stroke"` on the part itself: it works, but per-part outlines then
  cut black lines through joints between parts.

## Layer 2 — flat fills

- One flat colour (or a gentle two-stop vertical `linearGradient`, `x1=0 y1=0 x2=0 y2=1`,
  lighter at the top) per part.
- Tinted art: white to light grey (`#ffffff`→`#c4c4c4`); fixed-colour details mid grey or darker
  and masked.

## Layer 3 — shading, clipped to the part

```xml
<clipPath id="c-blade"><use xlink:href="#blade"/></clipPath>
<g clip-path="url(#c-blade)">
  <path d="…lower half…" fill="#000" opacity="0.08"/>     <!-- shade plane -->
  <path d="…upper facet…" fill="#fff" opacity="0.30"/>    <!-- light plane -->
</g>
```

- Shade and light shapes are simple planes (half the part, a band along the bottom edge, a
  facet), clipped so they never spill over the outline. Black/white at low opacity keeps the
  hue of the fill; on own-colour art prefer explicit darker/lighter hues of the same colour
  (more saturated in shadow, less in light), as in `resource_a.svg`.
- 2–3 value steps per part is the vanilla amount. Check with `analyze.py` `lum_range`.

## Layer 4 — inner lines and small details

- Seams, panel lines, plank gaps: 1–2 units, a darker shade of the local fill (`#9a9a9a` on
  a white blade, `#355727` on a green leaf), `stroke-linecap="round"`.
- Rivets and bolts: small circles, lighter than the surface, optionally a 1-unit darker ring.
- Anything smaller than ~2 px at the final texture size disappears after mipmapping; the
  starting-zoom preview row shows what survives.

## Painterly texture (plants, workbench tops, dirt)

Vanilla foliage and work surfaces have soft mottling. `feTurbulence` does it without bitmaps:

```xml
<filter id="grain" x="0" y="0" width="1" height="1">
  <feTurbulence type="fractalNoise" baseFrequency="0.12" numOctaves="3" seed="7" result="n"/>
  <feColorMatrix in="n" type="matrix"
    values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 -3 1.4" result="dark"/>
  <feComposite in="dark" in2="SourceAlpha" operator="in"/>
</filter>
<g id="art">…the drawing…</g>
<use xlink:href="#art" filter="url(#grain)" opacity="0.35"/>
```

The colour matrix turns noise into black with alpha = 1.4 − 3 × noise (blotches);
`feComposite in` keeps it inside the art's own alpha. Raise `baseFrequency` for finer grain,
change `seed` for variants (`Graphic_Random` sets), keep opacity ≤ 0.4.

## Reuse and variants

- `<use>` with `transform` for repeated pieces (stack items, leaves, rivets). Mirror with
  `scale(-1 1)` rather than rotating 180°, so a drooping leaf still droops.
- `Graphic_Multi`: one SVG per side (`X_north.svg`, `X_east.svg`, `X_south.svg`) sharing the
  same `<defs>` shapes; move features, not the camera. West is east mirrored unless the object
  is asymmetric in a way mirroring breaks (text-like details, handedness).
- Stack counts `_a/_b/_c`, random variants `A/B/C`: same piece defined once, different
  arrangements.

## Fitting apparel and pawn parts: guide underlays

Worn apparel sits on the same 128 px canvas as the body texture, one file per body type and
side. Put the vanilla body (extracted by `vanilla_tex.py`) underneath as a guide; any element
whose `id` starts with `guide` is removed by `render.py` before rasterising:

```xml
<image id="guide-body" opacity="0.4" width="128" height="128"
       xlink:href="C:/…/rimworld-svg-art/.cache/textures/png/core/things/pawn/humanlike/bodies/naked_male_south.png"/>
```

(absolute path with forward slashes; `vanilla_tex.py --path` prints the cache folder). Draw the
garment 2–6 units outside the body silhouette, shoulders and hem following it, collar opening
where the head goes (heads are a separate layer drawn on top). Draw it white; the colour comes
from stuff. Repeat for `Male Female Thin Hulk Fat` × `north east south`, moving the guide to
each body. A guide grid (`<g id="guide-grid">` of 1-unit lines every 16 units) helps align
multi-cell buildings the same way.

## Masks (`_m`, `…m`)

```xml
<svg … shape-rendering="crispEdges">
  <rect width="64" height="64" fill="#000"/>   <!-- keep own colour -->
  <rect … fill="#ff0000"/>                     <!-- colour one: stuff / colorOne -->
  <rect … fill="#00ff00"/>                     <!-- colour two: colorTwo -->
</svg>
```

Same viewBox and geometry as the texture, pure channel colours, no anti-aliasing
(`shape-rendering="crispEdges"` on the root). Rendered without colour bleed. Name them
`X_m` (Graphic_Single) or `X_southm` (Graphic_Multi, no underscore before `m`).

## Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Outline thinner than expected | stroke-width is the full width; half is hidden | double it |
| Black line through a joint | outlines drawn per part above other fills | one underlay group for all parts |
| Spiky corners on the outline | default miter join | `stroke-linejoin="round"` |
| Everything tinted, including steel parts | tinted shader without a mask | add `_m` mask, `shaderType` `CutoutComplex` |
| Coloured parts look muddy in game | own colour drawn on stuff-tinted art | grey it, or mask it black |
| Halo around the sprite zoomed out | transparent pixels' RGB leaks into mipmaps | leave `render.py`'s bleed on |
| resvg error "comment contains '--'" | `--` in a comment | reword |
| Filter does nothing | filter region clipped / `in2` wrong | `x="0" y="0" width="1" height="1"`, `in2="SourceAlpha"` |

## Generated SVG (sets, variants, tiling)

Hand-write one piece; when you need 5+ related files (rotations × fill levels, random variants,
stack sizes, tile runs), write a small Python generator in `workspace/<Mod>/Art/` that emits
the SVG text:

- **Constants first**: palette hexes, outline units, rim/post/board profile numbers at the top of
  the script — shared by every piece, so related parts cannot drift apart.
- **Helper functions return SVG strings** (`rect()`, `outline()`, `tuft()`, `pellet()`) and a
  `write(name, body)` that wraps them in the `<svg>` header. Keep coordinates in cell units.
- **Seeded randomness**: `random.Random(seed)` per piece, seed from the piece name, so reruns
  give identical output and the user's approved version is reproducible.
- **Output stays editable**: readable SVG with comments and grouped layers, so a single piece
  can still be hand-tuned (then fold the change back into the generator).
- Render the whole set with `render.py 'Art/svg/*.svg' --out …` and preview combinations with a
  `compose.py` scene the generator can also write.

## Tiling pieces (runs, linked atlases, floors)

- **Runs of 1-cell segments** (troughs, shelves joined in a row): anything crossing a cell
  edge must be drawn in both neighbours — draw each repeated detail at x and x ± 64. Mark the
  file `<!-- svg-art: allow edge -->`.
- **Linked atlas**: see `geometry.md` — 4×4 grid, bottom-up rows, only the centre 75 % of each
  sub-tile shows; boundary features are drawn as halves.
- **Seamless floor (1024 px = 16 cells)**: `feTurbulence … stitchTiles="stitch"` on a
  1024-unit filter region, and every shape that crosses an edge copied at ±1024 on that axis.
  Check by composing a 2×2 grid of the texture (`compose.py`, 4 layers) at the far zoom:
  visible repetition = too many distinct marks; reduce contrast of the largest features.
