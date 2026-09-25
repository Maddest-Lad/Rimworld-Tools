# /// script
# requires-python = ">=3.11"
# dependencies = ["resvg-py>=0.2", "Pillow>=10", "numpy>=1.26", "UnityPy>=1.20"]
# ///
"""Preview several textures together, laid out as the game would draw them.

    uv run compose.py scene.json [-o out.png]

For what a single-sprite `render.py --preview` cannot show: tiled runs with end caps, a storage
body with its fill layer on top, a Graphic_Linked fence pen, a door's movers + support + top,
a building next to vanilla neighbours. The scene is rendered at the camera's closest, starting
and far zoom (render.ZOOMS) once per tint, on real vanilla terrain.

Scene file (JSON; paths relative to it; .png or .svg — SVGs are rasterised on the fly):

    {
      "cells": [6, 3],                 scene size in map cells (x right, y DOWN)
      "bg": "soil",                    render.BACKGROUNDS name
      "tints": ["wood", "steel"],      one scene per tint; "stuff" layers take it
      "color_two": "#5b7fa8",          green-mask colour (optional)
      "ppc": 128,                      default texture px per cell for layers without "size"
      "layers": [                      drawn in order (later = on top)
        {"tex": "Trough/Trough_south.png", "at": [1, 1], "tint": "stuff"},
        {"tex": "Trough/TroughHay3_south.png", "at": [1, 1]},
        {"tex": "Stall/Stall_south.png", "center": [4, 1.5], "size": [2, 2], "tint": "stuff"},
        {"tex": "Door/Mover.png", "center": [2.25, 2.5], "size": [1, 1], "flip": true},
        {"linked": "Fence/Atlas.png", "cells": [[0,0],[1,0],[2,0],[0,1]], "links_to": [[3,0]],
         "tint": "stuff"},
        {"door": {"mover": "Door/Mover.png", "support": "Door/Support_south.png",
                  "top": "Door/Top_south.png"}, "center": [4, 0.5], "cells": 2, "axis": "x",
         "open": 0.0, "tint": "stuff", "top_size": [3, 1]},
        {"tex": "vanilla:core:things/building/furniture/endtable_south", "at": [5, 0],
         "size": [1, 1], "tint": "stuff"}
      ]
    }

Layer keys: `at` (top-left, cells) or `center` (cells; drawSize centred like the game);
`size` in cells (default: pixels / ppc); `tint`: "stuff" (the scene tint), "none" (default)
or a colour; `mask` (default: the X_m / X_southm sibling if present, applied like
CutoutComplex); `flip` (mirror, as for west); `rot` (degrees clockwise, for drawRotated
things); `alpha`. A `linked` layer picks each cell's sub-tile from a 4x4 Graphic_Linked atlas
from its neighbours in `cells` + `links_to` (cells it links to but does not draw, e.g. a
gate in a fence line; see reference/geometry.md), drawn over 1x1 cell. A `linked` layer
may have a `mask` atlas (cropped the same way). A `door` layer expands to both leaves (the second
mirrored) at the engine's offsets for `open` 0..1, plus optional support and top textures —
`cells` (door width along its axis), `axis` "x" (south-facing) or "y" (east-facing),
`support_size`/`top_size`/`…_offset` in cells. A `tex` of `vanilla:<src:path>` pulls a
Core/DLC texture through vanilla_tex.py — always Ludeon's original, never a texture-replacement
mod's; to preview a replacement (e.g. Gerrymon's), give that mod file's path instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render

# ---------------------------------------------------------------- loading


def load_tex(ref: str, base: Path) -> tuple[Image.Image, Path | None]:
    if ref.startswith("vanilla:"):
        import vanilla_tex as vt

        key = ref[len("vanilla:") :]
        hits = [e for e in vt.load_index() if vt.key(e) == key]
        if not hits:
            raise SystemExit(f"no vanilla texture {key!r} (vanilla_tex.py --search)")
        path = vt.extract(hits, vt.CACHE / "png")[0]
        return Image.open(path).convert("RGBA"), path
    path = (base / ref).resolve()
    if not path.exists():
        raise SystemExit(f"layer texture not found: {path}")
    if path.suffix.lower() == ".svg":
        return render.rasterise(path, None), path
    return Image.open(path).convert("RGBA"), path


def find_mask(path: Path | None) -> Image.Image | None:
    if path is None:
        return None
    for stem in render.mask_names(path.stem):
        for ext in (".png", ".svg"):
            m = path.with_name(stem + ext)
            if m.exists():
                return render.rasterise(m, None) if ext == ".svg" else Image.open(m)
    return None


# ---------------------------------------------------------------- linked atlas


def link_index(cell: tuple[int, int], cells: set[tuple[int, int]]) -> int:
    """Graphic_Linked: bit 1 north, 2 east, 4 south, 8 west (GenAdj.CardinalDirections order).
    Scene y runs down, so north is y - 1."""
    x, y = cell
    n = 0
    for bit, (dx, dy) in zip((1, 2, 4, 8), ((0, -1), (1, 0), (0, 1), (-1, 0))):
        if (x + dx, y + dy) in cells:
            n += bit
    return n


def atlas_tile(atlas: Image.Image, index: int) -> Image.Image:
    """MaterialAtlasPool: 4x4 grid, column i%4, row i//4 counted from the BOTTOM; each sub-
    material shows only the central 0.1875 of the 0.25 tile (offset 1/32)."""
    w, h = atlas.size
    col, row_b = index % 4, index // 4
    u0, v0 = col * 0.25 + 1 / 32, row_b * 0.25 + 1 / 32
    x0, x1 = round(u0 * w), round((u0 + 0.1875) * w)
    y1, y0 = round((1 - v0) * h), round((1 - v0 - 0.1875) * h)
    return atlas.crop((x0, y0, x1, y1))


# ---------------------------------------------------------------- drawing


def parse_colour(spec: str | None, scene_tint: tuple[int, int, int]) -> tuple[int, int, int]:
    if not spec or spec == "none":
        return (255, 255, 255)
    if spec == "stuff":
        return scene_tint
    return render.parse_tints(spec)[0][1]


def place(
    canvas: Image.Image,
    im: Image.Image,
    ppc: int,
    size: tuple[float, float],
    at: tuple[float, float] | None = None,
    center: tuple[float, float] | None = None,
    rot: float = 0,
    alpha: float = 1.0,
) -> None:
    w, h = max(1, round(size[0] * ppc)), max(1, round(size[1] * ppc))
    im = im.resize((w, h), Image.LANCZOS)
    if rot:
        im = im.rotate(-rot, resample=Image.BICUBIC, expand=True)
    if alpha < 1:
        a = im.getchannel("A").point(lambda v: round(v * alpha))
        im.putalpha(a)
    if center is not None:
        x, y = center[0] * ppc - im.width / 2, center[1] * ppc - im.height / 2
    else:
        x, y = at[0] * ppc, at[1] * ppc  # type: ignore[index]
    layer = Image.new("RGBA", canvas.size)
    layer.paste(im, (round(x), round(y)), im)
    canvas.alpha_composite(layer)


def draw_scene(scene: dict, prepared: list[dict], tint, ppc: int) -> Image.Image:
    cw, ch = scene["cells"]
    canvas = render.background(scene.get("bg", "soil"), round(cw * ppc), round(ch * ppc), ppc)
    two = render.parse_tints(scene.get("color_two", "#5b7fa8"))[0][1]
    for L in prepared:
        rgb = parse_colour(L.get("tint"), tint)
        if "tiles" in L:
            for (x, y), tile, mtile in L["tiles"]:
                place(canvas, render.colorize(tile, rgb, mtile, two), ppc, (1, 1), at=(x, y))
            continue
        im = render.colorize(L["im"], rgb, L["mask"], two)
        if L.get("flip"):
            im = im.transpose(Image.FLIP_LEFT_RIGHT)
        place(
            canvas,
            im,
            ppc,
            L["size"],
            L.get("at"),
            L.get("center"),
            L.get("rot", 0),
            L.get("alpha", 1.0),
        )
    return canvas


def door_layers(L: dict) -> list[dict]:
    """Expand a `door` layer into plain layers, following Building_Door.DrawMovers.

    1-cell door: leaves full size, each offset 0.45 x open. Multi-cell (Building_MultiTileDoor):
    each leaf is half the door wide, offset n x (0.25 + 0.35 x open). The unflipped leaf goes to
    the -axis side (left / up), the mirrored copy to the + side. axis "y" (east-facing door): the
    leaf quad turns with the door, so the leaf texture is rotated 90 degrees clockwise.
    Then doorSupportGraphic and doorTopGraphic, centred, drawn above the leaves."""
    d = L["door"]
    n = L.get("cells", 1)
    cx, cy = L["center"]
    opened = L.get("open", 0.0)
    y_axis = L.get("axis", "x") == "y"
    if n == 1:
        leaf, off = [1.0, 1.0], 0.45 * opened
    else:
        leaf, off = [n * 0.5, 1.0], n * (0.25 + 0.35 * opened)
    common = {k: L[k] for k in ("tint", "mask") if k in L}
    out = []
    for sign, flip in ((-1, False), (1, True)):
        pos = [cx, cy + sign * off] if y_axis else [cx + sign * off, cy]
        out.append(
            {
                "tex": d["mover"],
                "center": pos,
                "size": leaf,
                "flip": flip,
                "rot": 90 if y_axis else 0,
                **common,
            }
        )
    full = [1, n] if y_axis else [n, 1]
    for part in ("support", "top"):
        if part in d:
            ox, oy = L.get(f"{part}_offset", [0, 0])
            out.append(
                {
                    "tex": d[part],
                    "center": [cx + ox, cy + oy],
                    "size": L.get(f"{part}_size", full),
                    **common,
                }
            )
    return out


def prepare(scene: dict, base: Path) -> list[dict]:
    out = []
    default_ppc = scene.get("ppc", 64)
    layers = []
    for L in scene["layers"]:
        layers.extend(door_layers(L) if "door" in L else [L])
    for L in layers:
        L = dict(L)
        if "linked" in L:
            atlas, _ = load_tex(L["linked"], base)
            matlas = load_tex(L["mask"], base)[0] if "mask" in L else None
            cells = {tuple(c) for c in L["cells"]}
            links = cells | {tuple(c) for c in L.get("links_to", [])}
            L["tiles"] = []
            for c in sorted(cells):
                i = link_index(c, links)
                L["tiles"].append((c, atlas_tile(atlas, i), matlas and atlas_tile(matlas, i)))
        else:
            L["im"], path = load_tex(L["tex"], base)
            if "mask" in L:
                L["mask"] = load_tex(L["mask"], base)[0]
            else:
                L["mask"] = find_mask(path)
            if "size" not in L:
                L["size"] = [L["im"].width / default_ppc, L["im"].height / default_ppc]
            if "at" not in L and "center" not in L:
                L["at"] = [0, 0]
        out.append(L)
    return out


def compose(scene: dict, base: Path, screen: int = 1440) -> Image.Image:
    prepared = prepare(scene, base)
    tints = render.parse_tints(",".join(scene.get("tints", ["white"])))
    pad, label = 10, 14
    rows = []
    for zname, ortho in render.ZOOMS:
        ppc = round(screen / (2 * ortho))
        panels = [(t, draw_scene(scene, prepared, rgb, ppc)) for t, rgb in tints]
        rows.append((f"{zname} zoom, {ppc} px/cell", panels))
    W = max(sum(p.width + pad for _, p in panels) + pad for _, panels in rows)
    H = sum(max(p.height for _, p in panels) + label * 2 + pad for _, panels in rows)
    sheet = Image.new("RGBA", (W, H), (30, 30, 30, 255))
    d = ImageDraw.Draw(sheet)
    y = 0
    for title, panels in rows:
        d.text((pad, y + 2), title, fill=(230, 230, 230, 255))
        x, rh = pad, max(p.height for _, p in panels)
        for name, p in panels:
            sheet.alpha_composite(p, (x, y + label))
            d.text((x, y + label + rh + 2), name, fill=(230, 230, 230, 255))
            x += p.width + pad
        y += rh + label * 2 + pad
    return sheet


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("scene", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="default: <scene>.png next to the JSON")
    ap.add_argument("--screen", type=int, default=1440)
    a = ap.parse_args(argv)
    scene = json.loads(a.scene.read_text(encoding="utf-8"))
    sheet = compose(scene, a.scene.parent, a.screen)
    out = a.out or a.scene.with_suffix(".png")
    sheet.save(out)
    print(f"compose -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
