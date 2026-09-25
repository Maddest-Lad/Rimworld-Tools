# /// script
# requires-python = ">=3.11"
# dependencies = ["resvg-py>=0.2", "Pillow>=10", "numpy>=1.26", "UnityPy>=1.20"]
# ///
"""Rasterise hand-written SVGs to game-ready PNGs, lint them, and preview them as the game would.

    uv run render.py art/Sword.svg                          # -> art/Sword.png (size from the SVG)
    uv run render.py art/*.svg --out workspace/MyMod/Textures/MyMod/Things/Item
    uv run render.py art/Bed_*.svg --size 128               # force output size (square)
    uv run render.py art/Sword.svg --preview                # + art/Sword.preview.png
    uv run render.py art/Chair_south.svg --preview --draw-size 1 --tint steel,wood,#b43c3c \
        --ref 'core:things/building/furniture/.*chair_south' --bg soil,concrete
    uv run render.py art/Sword.svg --lint-only              # checks, no files written

Elements whose id starts with `guide` (a vanilla body under apparel, a cell grid) are removed
before rendering, so reference underlays never reach the PNG.

Output PNGs get a colour bleed: fully transparent pixels take the colour of the nearest opaque
pixel, so mipmaps (the game uses trilinear + DXT, see reference/technical.md) do not pull
black or white halos into the edge. `--no-bleed` disables it.

Lint (always runs): ERROR if a side is not a multiple of 4 (no compression). Warnings carry a
code — [pow2] not a power of two, [edge] content touches the canvas edge, [faint] haze,
[outline] no dark edge, [mask] impure mask colours — and notes [multi] for Graphic_Multi sides
the game will substitute. Accept intended ones per file with a comment anywhere in the SVG,
`<!-- svg-art: allow edge, outline -->`, or for the run with `--allow edge,pow2`.

Preview (`--preview [FILE]`): a sheet with the sprite on checkerboard at native size, then on
real vanilla terrain at the camera's closest, starting and a far zoom (orthographic size 11,
24 and 60 cells: 65, 30 and 12 screen px per cell at `--screen 1440`; 49/22/9 at 1080),
multiplied by each `--tint` (stuff colour: a name from STUFF below or #rrggbb) — the way
`Cutout` shaders tint white art. A mask rendered in the same run (`X_southm` for `X_south`,
`X_m` for `X`) is applied like `CutoutComplex`: red takes the tint, green `--color-two`, black
keeps its own colour. `--ref` adds vanilla sprites (vanilla_tex.py regex, extracted on demand,
with their masks) at the same on-map scale; `--ref-draw-size auto` sizes them at 64 px/cell.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

STUFF = {  # stuffProps/color of vanilla materials, 1.6.4871
    "white": (255, 255, 255),
    "steel": (105, 105, 105),
    "wood": (133, 97, 67),
    "plasteel": (160, 178, 181),
    "gold": (255, 235, 122),
    "silver": (180, 173, 150),
    "uranium": (100, 100, 100),
    "jade": (85, 118, 69),
    "granite": (105, 95, 97),
    "marble": (132, 135, 132),
    "slate": (70, 70, 70),
    "sandstone": (126, 104, 94),
    "limestone": (158, 153, 135),
    "cloth": (162, 157, 152),
    "leather": (162, 106, 57),
    "devilstrand": (180, 60, 60),
    "hyperweave": (0, 106, 126),
    "synthread": (174, 219, 228),
}
BACKGROUNDS = {  # vanilla terrain texture, multiply colour, flat fallback
    "soil": ("core:terrain/surfaces/soil$", (255, 255, 255), (110, 94, 72)),
    "gravel": ("core:terrain/surfaces/gravel$", (255, 255, 255), (122, 116, 104)),
    "concrete": ("core:terrain/surfaces/concrete$", (140, 140, 140), (120, 120, 118)),
    "sand": ("core:terrain/surfaces/sand$", (255, 255, 255), (190, 170, 130)),
    "wood": ("core:terrain/surfaces/woodfloor$", (133, 97, 67), (110, 80, 55)),
    "dark": (None, None, (40, 40, 40)),
}
# CameraMapConfig.sizeRange 11..60, CameraDriver.StartingSize 24 (orthographic half-height, cells)
ZOOMS = (("closest", 11.0), ("starting", 24.0), ("far", 60.0))
SIDES = ("north", "east", "south", "west")


# ---------------------------------------------------------------- rasterise


def svg_size(svg: str) -> tuple[int, int] | None:
    head = svg[: svg.find(">", svg.find("<svg")) + 1]

    def attr(name: str) -> float | None:
        m = re.search(rf'\b{name}="([\d.]+)(?:px)?"', head)
        return float(m.group(1)) if m else None

    w, h = attr("width"), attr("height")
    if w and h:
        return round(w), round(h)
    m = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', head)
    return (round(float(m.group(1))), round(float(m.group(2)))) if m else None


def strip_guides(svg: str) -> str:
    """Drop elements whose id starts with "guide" (reference underlays, grids) before rendering."""
    if 'id="guide' not in svg:
        return svg
    import xml.etree.ElementTree as ET

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    root = ET.fromstring(svg)
    for parent in root.iter():
        for child in list(parent):
            if child.get("id", "").startswith("guide"):
                parent.remove(child)
    return ET.tostring(root, encoding="unicode")


def rasterise(svg_path: Path, size: tuple[int, int] | None) -> Image.Image:
    import io

    import resvg_py

    svg = strip_guides(svg_path.read_text(encoding="utf-8"))
    native = svg_size(svg)
    target = size or native
    if target is None:
        raise SystemExit(f"{svg_path}: no width/height/viewBox; pass --size")
    kw: dict = {"svg_string": svg, "resources_dir": str(svg_path.parent.resolve())}
    if native and target != native:
        kw["width"], kw["height"] = target
    try:
        png = bytes(resvg_py.svg_to_bytes(**kw))
    except ValueError as e:  # XML/SVG parse errors, e.g. '--' inside a comment
        raise SystemExit(f"{svg_path}: {e}") from None
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    if im.size != tuple(target):
        im = im.resize(target, Image.LANCZOS)
    return im


def bleed(im: Image.Image, passes: int = 16) -> Image.Image:
    """Give transparent pixels the colour of their nearest opaque neighbours (alpha unchanged)."""
    a = np.asarray(im).astype(np.float32)
    rgb, alpha = a[..., :3].copy(), a[..., 3]
    known = alpha > 0
    for _ in range(passes):
        if known.all():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(alpha.shape, np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(rgb, (dy, dx), (0, 1)) * k[..., None]
            cnt += k
        grow = ~known & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow][:, None]
        known = known | grow
    out = np.dstack([rgb, alpha]).clip(0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


# ---------------------------------------------------------------- lint


def is_pow2(n: int) -> bool:
    return n > 0 and n & (n - 1) == 0


def is_mask(path: Path) -> bool:
    return bool(re.search(r"(_m|(north|east|south|west)m)$", path.stem))


LINT_CODES = {
    "pow2": "size not a power of two (vanilla ships some: fence atlas 640, door top 192x128)",
    "edge": "content touches the canvas edge (intended for tileable / linked / seamless pieces)",
    "faint": "many nearly transparent pixels (intended for glows, mist, shadows)",
    "outline": "no dark edge (intended for overlay layers drawn inside another sprite's outline)",
    "mask": "mask not pure channel colours",
    "multi": "Graphic_Multi side missing (the game falls back, see lint_multi)",
}
ALLOW_RE = re.compile(r"svg-art:\s*allow\s+([a-z0-9, ]+)", re.IGNORECASE)


def allowed_codes(svg_text: str) -> set[str]:
    """Codes from `<!-- svg-art: allow edge, outline -->` comments in the SVG."""
    out: set[str] = set()
    for m in ALLOW_RE.finditer(svg_text):
        out |= {c.strip().lower() for c in m.group(1).split(",") if c.strip()}
    return out


def lint(im: Image.Image, name: str, allow: set[str] | frozenset = frozenset()) -> list[str]:
    """ERROR lines always; `warn  [code] ...` lines unless the code is allowed."""
    w, h = im.size
    out = []

    def warn(code: str, msg: str) -> None:
        if code not in allow:
            out.append(f"warn  [{code}] {msg}")

    if w % 4 or h % 4:
        out.append(f"ERROR size {w}x{h} is not a multiple of 4: the game skips compression")
    elif not (is_pow2(w) and is_pow2(h)):
        warn("pow2", f"size {w}x{h} is not a power of two: fewer mipmaps, blurrier far out")
    a = np.asarray(im)
    alpha = a[..., 3]
    if (alpha > 0).sum() == 0:
        return out + ["ERROR fully transparent"]
    if is_mask(Path(name)):
        rgb = a[..., :3][alpha > 0].astype(int)
        pure = np.isin(rgb, (0, 255)).all(axis=1).mean()
        if pure < 0.9:
            warn("mask", f"mask: only {pure:.0%} of pixels are pure channel colours")
        return out
    edge = np.concatenate([alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]])
    if (edge > 16).any():
        warn("edge", "content touches the canvas edge (outline or AA will be cut off)")
    faint = ((alpha > 0) & (alpha < 40)).sum() / max((alpha > 0).sum(), 1)
    if faint > 0.15:
        warn("faint", f"{faint:.0%} of visible pixels are nearly transparent (haze/glow?)")
    from analyze import analyze_image

    r = analyze_image(im)
    if not r.get("empty") and r["outline_px"] == 0 and r["edge_ratio"] > 0.85:
        warn(
            "outline",
            f"no dark edge (edge_ratio {r['edge_ratio']}): things and icons have a black "
            "outline, plants a darker shade of their own colour",
        )
    return out


def lint_multi(paths: list[Path], allow: set[str] | frozenset = frozenset()) -> list[str]:
    """Notes on Graphic_Multi sets. Missing sides are legal (Graphic_Multi.Init): no _north ->
    south is used; no _east -> _west mirrored, else north; no _west -> _east mirrored."""
    if "multi" in allow:
        return []
    groups: dict[tuple[Path, str], set[str]] = {}
    for p in paths:
        m = re.match(r"(.+)_(north|east|south|west)$", p.stem)
        if m:
            groups.setdefault((p.parent, m.group(1)), set()).add(m.group(2))
    out = []
    for (_, base), sides in groups.items():
        notes = []
        if "north" not in sides:
            notes.append("no _north: the game shows _south for north")
        if "east" not in sides and "west" not in sides:
            notes.append("no _east/_west: the game shows _north for east and west")
        if notes:
            out.append(f"note  [multi] {base}: " + "; ".join(notes) + " (fine if intended)")
    return out


# ---------------------------------------------------------------- preview


def parse_tints(spec: str) -> list[tuple[str, tuple[int, int, int]]]:
    tints = []
    for t in filter(None, (s.strip() for s in spec.split(","))):
        if t.lower() in STUFF:
            tints.append((t.lower(), STUFF[t.lower()]))
        elif re.fullmatch(r"#?[0-9a-fA-F]{6}", t):
            h = t.lstrip("#")
            tints.append((f"#{h}", tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))))
        else:
            raise SystemExit(f"unknown tint {t!r}: use #rrggbb or one of {', '.join(STUFF)}")
    return tints


def multiply(im: Image.Image, rgb: tuple[int, int, int]) -> Image.Image:
    if rgb == (255, 255, 255):
        return im
    a = np.asarray(im).astype(np.float32)
    a[..., :3] *= np.array(rgb, np.float32) / 255.0
    return Image.fromarray(a.clip(0, 255).astype(np.uint8), "RGBA")


def colorize(
    im: Image.Image,
    rgb: tuple[int, int, int],
    mask: Image.Image | None = None,
    rgb2: tuple[int, int, int] = (255, 255, 255),
) -> Image.Image:
    """Approximate the game's tint: `Cutout` multiplies everything by the colour; with a mask
    (`CutoutComplex`) red selects colour one, green colour two, black keeps the texture's own."""
    if mask is None:
        return multiply(im, rgb)
    a = np.asarray(im).astype(np.float32)
    m = np.asarray(mask.convert("RGB").resize(im.size, Image.BILINEAR)).astype(np.float32) / 255
    one = np.array(rgb, np.float32) / 255.0
    two = np.array(rgb2, np.float32) / 255.0
    r, g = m[..., 0:1], m[..., 1:2]
    a[..., :3] *= (1 - r + r * one) * (1 - g + g * two)
    return Image.fromarray(a.clip(0, 255).astype(np.uint8), "RGBA")


def checker(w: int, h: int, s: int = 8) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w]
    v = np.where(((xx // s) + (yy // s)) % 2, 200, 160).astype(np.uint8)
    return Image.fromarray(np.dstack([v, v, v, np.full_like(v, 255)]), "RGBA")


def background(name: str, w: int, h: int, px_per_cell: int) -> Image.Image:
    tex_re, mul, flat = BACKGROUNDS[name]
    tile = None
    if tex_re:
        try:
            import vanilla_tex as vt

            hits = vt.search(vt.load_index(), tex_re)
            if hits:
                tile = Image.open(vt.extract(hits[:1], vt.CACHE / "png")[0]).convert("RGBA")
        except Exception as e:  # noqa: BLE001 - no game files / UnityPy failure: flat colour
            print(f"(background {name}: {e}; using a flat colour)", file=sys.stderr)
    if tile is None:
        return Image.new("RGBA", (w, h), flat + (255,))
    # vanilla terrain textures repeat every 16 cells (1024 px -> 64 px/cell)
    scale = px_per_cell / (tile.width / 16)
    tile = multiply(tile.resize((max(1, round(tile.width * scale)),) * 2, Image.LANCZOS), mul)
    bg = Image.new("RGBA", (w, h))
    for y in range(0, h, tile.height):
        for x in range(0, w, tile.width):
            bg.paste(tile, (x, y))
    return bg


def on_map(im: Image.Image, draw_size: tuple[float, float], px_per_cell: int) -> Image.Image:
    w = max(1, round(draw_size[0] * px_per_cell))
    h = max(1, round(draw_size[1] * px_per_cell))
    return im.resize((w, h), Image.LANCZOS)


def mask_names(stem: str) -> list[str]:
    """Mask stems the game looks for: Graphic_Multi `X_south` -> `X_southm`; Single `X` -> `X_m`."""
    if re.search(r"_(north|east|south|west)$", stem):
        return [stem + "m"]
    return [stem + "_m"]


def pair_masks(sprites: list[tuple[str, Image.Image]]) -> list[dict]:
    by = dict(sprites)
    out = []
    for n, im in sprites:
        if is_mask(Path(n)):
            continue
        mask = next((by[m] for m in mask_names(n) if m in by), None)
        out.append({"name": n, "im": im, "mask": mask})
    return out


def ref_images(pattern: str | None, limit: int) -> list[tuple[str, Image.Image]]:
    """Vanilla sprites matching the regex (masks excluded), plus their masks when they exist."""
    if not pattern:
        return []
    import vanilla_tex as vt

    index = vt.load_index()
    hits = [h for h in vt.search(index, pattern) if not is_mask(Path(h["path"]))][:limit]
    wanted = {
        (h["src"], h["path"][: h["path"].rfind("/") + 1] + m)
        for h in hits
        for m in mask_names(Path(h["path"]).name)
    }
    masks = [e for e in index if (e["src"], e["path"]) in wanted]
    files = vt.extract(hits + masks, vt.CACHE / "png")
    return [(Path(f).stem, Image.open(f).convert("RGBA")) for f in files]


def preview(
    items: list[dict],
    refs: list[dict],
    draw_size: tuple[float, float],
    ref_draw_size: tuple[float, float] | None,
    tints: list[tuple[str, tuple[int, int, int]]],
    bgs: list[str],
    tint_refs: bool = False,
    color_two: tuple[int, int, int] = (255, 255, 255),
    screen_h: int = 1440,
) -> Image.Image:
    """Sheet: native size on checkerboard, then on terrain at each camera zoom and tint.
    ref_draw_size None = each ref's pixel size / 64 (right for vanilla buildings and items)."""
    pad, label = 10, 14

    def rdraw(im: Image.Image) -> tuple[float, float]:
        return ref_draw_size or (im.width / 64, im.height / 64)

    native = [(s["name"], s["im"]) for s in items] + [(f"ref {s['name']}", s["im"]) for s in refs]
    rows: list[dict] = [{"title": "native px (checkerboard)", "cells": native, "bg": None}]
    for zname, ortho in ZOOMS:
        ppc = round(screen_h / (2 * ortho))
        for bg in bgs:
            cells = [
                (
                    f"{s['name']} {tname}",
                    on_map(colorize(s["im"], rgb, s["mask"], color_two), draw_size, ppc),
                )
                for tname, rgb in tints
                for s in items
            ]
            ref_tints = tints if tint_refs else [("", (255, 255, 255))]
            cells += [
                (
                    f"ref {s['name']} {tname}".rstrip(),
                    on_map(colorize(s["im"], rgb, s["mask"], color_two), rdraw(s["im"]), ppc),
                )
                for tname, rgb in ref_tints
                for s in refs
            ]
            rows.append(
                {
                    "title": f"{zname} zoom, {ppc} px/cell, {bg}",
                    "cells": cells,
                    "bg": bg,
                    "ppc": ppc,
                }
            )
    for row in rows:
        row["w"] = sum(max(im.width, 60) + pad for _, im in row["cells"]) + pad
        row["h"] = max(im.height for _, im in row["cells"]) + label * 2 + pad
    W, H = max(r["w"] for r in rows), sum(r["h"] for r in rows)
    sheet = Image.new("RGBA", (W, H), (30, 30, 30, 255))
    d = ImageDraw.Draw(sheet)
    y = 0
    for row in rows:
        rh, cells = row["h"], row["cells"]
        top = y + label
        if row["bg"]:
            sheet.alpha_composite(background(row["bg"], W, rh - label, row["ppc"]), (0, top))
        d.text((pad, y + 2), row["title"], fill=(230, 230, 230, 255))
        x = pad
        for name, im in cells:
            cw = max(im.width, 60)
            if not row["bg"]:
                sheet.alpha_composite(
                    checker(im.width, im.height), (x + (cw - im.width) // 2, top + 2)
                )
            sheet.alpha_composite(im, (x + (cw - im.width) // 2, top + 2))
            d.text(
                (x, top + rh - label * 2 - pad + 4),
                name[: max(8, cw // 6)],
                fill=(255, 255, 255, 255),
                stroke_width=1,
                stroke_fill=(0, 0, 0, 255),
            )
            x += cw + pad
        y += rh
    return sheet


# ---------------------------------------------------------------- main


def parse_pair(s: str) -> tuple[float, float]:
    parts = [float(v) for v in re.split(r"[,x ]+", s.strip("() "))]
    return (parts[0], parts[-1])


def expand(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in patterns:
        hits = sorted(Path().glob(p)) if any(c in p for c in "*?[") else [Path(p)]
        out.extend(h for h in hits if h.suffix.lower() == ".svg")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("svgs", nargs="+", help="SVG files or globs")
    ap.add_argument("--out", type=Path, help="output folder (default: next to each SVG)")
    ap.add_argument("--size", help="output size, e.g. 128 or 256x128 (default: SVG width/height)")
    ap.add_argument("--no-bleed", action="store_true")
    ap.add_argument("--lint-only", action="store_true")
    ap.add_argument(
        "--allow",
        type=lambda v: [c.strip() for c in v.split(",") if c.strip()],
        default=[],
        help=f"comma list of lint codes to accept: {', '.join(LINT_CODES)} "
        "(or per file: <!-- svg-art: allow edge, outline -->)",
    )
    ap.add_argument(
        "--preview",
        nargs="?",
        const="",
        metavar="FILE",
        help="write a preview sheet (default: <first>.preview.png)",
    )
    ap.add_argument("--draw-size", default="1", help="graphicData drawSize in cells (default 1)")
    ap.add_argument("--tint", default="white", help="comma list: stuff names or #rrggbb")
    ap.add_argument("--bg", default="soil,concrete", help=f"comma list of {', '.join(BACKGROUNDS)}")
    ap.add_argument("--ref", metavar="REGEX", help="vanilla textures to show alongside")
    ap.add_argument(
        "--ref-draw-size",
        help="drawSize for --ref sprites; 'auto' = pixels / 64 "
        "(right for vanilla buildings and items; default: --draw-size)",
    )
    ap.add_argument("--ref-limit", type=int, default=4)
    ap.add_argument("--tint-refs", action="store_true", help="apply --tint to --ref sprites too")
    ap.add_argument(
        "--color-two",
        default="#5b7fa8",
        help="colour for green mask areas (colorTwo); default a muted blue",
    )
    ap.add_argument(
        "--screen", type=int, default=1440, help="screen height for the zoom rows (default 1440)"
    )
    a = ap.parse_args(argv)

    svgs = expand(a.svgs)
    if not svgs:
        print("no .svg files matched", file=sys.stderr)
        return 2
    size = None
    if a.size:
        w, h = parse_pair(a.size)
        size = (int(w), int(h))
    problems = 0
    rendered: list[tuple[str, Image.Image]] = []
    for svg in svgs:
        im = rasterise(svg, size)
        allow = set(a.allow) | allowed_codes(svg.read_text(encoding="utf-8"))
        issues = lint(im, svg.stem, allow)
        problems += sum(i.startswith("ERROR") for i in issues)
        dest = (a.out or svg.parent) / (svg.stem + ".png")
        if not a.lint_only:
            dest.parent.mkdir(parents=True, exist_ok=True)
            (im if a.no_bleed or is_mask(svg) else bleed(im)).save(dest)
        print(f"{svg} -> {dest if not a.lint_only else '(lint only)'}  {im.width}x{im.height}")
        for i in issues:
            print(f"  {i}")
        rendered.append((svg.stem, im))
    for i in lint_multi(svgs, set(a.allow)):
        print(i)

    if a.preview is not None:
        draw = parse_pair(a.draw_size)
        ref_draw = (
            None
            if a.ref_draw_size == "auto"
            else (parse_pair(a.ref_draw_size) if a.ref_draw_size else draw)
        )
        bgs = [b.strip() for b in a.bg.split(",") if b.strip()]
        bad = [b for b in bgs if b not in BACKGROUNDS]
        if bad:
            raise SystemExit(f"unknown --bg {bad}; choose from {', '.join(BACKGROUNDS)}")
        sheet = preview(
            pair_masks(rendered),
            pair_masks(ref_images(a.ref, a.ref_limit)),
            draw,
            ref_draw,
            parse_tints(a.tint),
            bgs,
            a.tint_refs,
            parse_tints(a.color_two)[0][1],
            a.screen,
        )
        dest = Path(a.preview) if a.preview else svgs[0].with_suffix(".preview.png")
        sheet.save(dest)
        print(f"preview -> {dest}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
