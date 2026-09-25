# /// script
# requires-python = ">=3.11"
# dependencies = ["Pillow>=10", "numpy>=1.26"]
# ///
"""Measure a sprite's style numbers: outline, palette, value/saturation, coverage.

    uv run analyze.py sprite.png [more.png ...]         # one report per file
    uv run analyze.py 'glob/**/*.png' --summary         # medians over many files (a style baseline)
    uv run analyze.py mine.png --against 'ref/*.png'    # mine vs reference medians, flags outliers
    uv run analyze.py mine.png --against 'ref/*.png' --ppc 128 --ref-ppc 64
                                                        # different texture densities: compare
                                                        # outline and margin per map cell
    uv run analyze.py ... --json

Use it on extracted vanilla textures (vanilla_tex.py) to learn a category's conventions, and on
your own rendered PNGs to check they sit inside them. Measurements:

- outline_px    rings of edge pixels (from the alpha edge inward) darker than 45 % of the
                interior's median luminance; scale-free as outline_rel = outline_px / sprite size
- outline_rgb   mean colour of the outer ring
- edge_ratio    outer ring luminance / interior luminance: ~0 for black-outlined things,
                ~0.45-0.95 for plants (a darker shade of their own colour, no black line)
- lum / sat     median luminance (0-1, Rec.601) and HSV saturation of the interior
                (pixels 6+ px inside the edge; the whole sprite if that leaves too few)
- lum_range     10th-90th percentile luminance spread of the interior (shading contrast)
- palette       dominant interior colours (median-cut, 6) with their share
- coverage      opaque share of the canvas; bbox of opaque pixels; minimum margin in px
- soft_edge     share of edge pixels with partial alpha (anti-aliasing)
- outline_cell  with --ppc: outline in px at 64 px per cell (vanilla buildings 2-3)
- margin_cell   with --ppc: transparent margin in cells

outline_rel and margin_rel are relative to the canvas, so they only compare sprites of the same
footprint and density. When yours is 128 px/cell and the references 64 (or a 2x2 bed against
1x1 tables), pass --ppc/--ref-ppc: the comparison then uses outline_cell and margin_cell instead.
"""

from __future__ import annotations

import argparse
import glob
import json
import statistics
import sys
from pathlib import Path

import numpy as np
from PIL import Image

KEYS = (
    "outline_px",
    "outline_rel",
    "edge_ratio",
    "lum",
    "sat",
    "lum_range",
    "coverage",
    "margin_rel",
)


def erode(mask: np.ndarray) -> np.ndarray:
    m = mask.copy()
    m[1:, :] &= mask[:-1, :]
    m[:-1, :] &= mask[1:, :]
    m[:, 1:] &= mask[:, :-1]
    m[:, :-1] &= mask[:, 1:]
    m[0, :] = m[-1, :] = m[:, 0] = m[:, -1] = False
    return m


def hexrgb(rgb) -> str:
    r, g, b = (int(v) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def luminance(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114) / 255.0


def saturation(rgb: np.ndarray) -> np.ndarray:
    mx = rgb.max(axis=-1).astype(float)
    mn = rgb.min(axis=-1).astype(float)
    return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0.0)


def analyze(path: str | Path) -> dict:
    return {"file": str(path), **analyze_image(Image.open(path))}


def analyze_image(im: Image.Image) -> dict:
    a = np.asarray(im.convert("RGBA"))
    rgb, alpha = a[..., :3].astype(float), a[..., 3]
    h, w = alpha.shape
    mask = alpha > 127
    out: dict = {"size": [w, h]}
    if mask.sum() < 16:
        out["empty"] = True
        return out
    rings = []
    cur, interior = mask, mask
    for i in range(12):
        nxt = erode(cur)
        ring = cur & ~nxt
        if not ring.any():
            break
        rings.append(ring)
        cur = nxt
        if i == 5 and cur.sum() >= 16:
            interior = cur  # 6 px in: past any vanilla outline, still thick enough to sample
    lum = luminance(rgb)
    in_lum = lum[interior]
    ref = float(np.median(in_lum))
    thick = 0
    for ring in rings:
        if np.median(lum[ring]) < 0.45 * ref + 0.02:
            thick += 1
        else:
            break
    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    margin = min(x0, y0, w - 1 - x1, h - 1 - y1)
    edge = mask & ~erode(mask)
    near = np.zeros_like(mask)
    near[1:, :] |= edge[:-1, :]
    near[:-1, :] |= edge[1:, :]
    near[:, 1:] |= edge[:, :-1]
    near[:, :-1] |= edge[:, 1:]
    band = (near | edge) & (alpha > 0)
    soft = float(((alpha > 8) & (alpha < 247) & band).sum() / max(band.sum(), 1))
    body = rgb[interior].astype(np.uint8).reshape(-1, 1, 3)
    q = Image.fromarray(body, "RGB").quantize(6, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[:18]
    counts = sorted(q.getcolors() or [], reverse=True)
    total = sum(c for c, _ in counts)
    palette = [(hexrgb(pal[i * 3 : i * 3 + 3]), round(c / total, 3)) for c, i in counts]
    out.update(
        outline_px=thick,
        outline_rel=round(thick / max(w, h), 4),
        outline_rgb=hexrgb(rgb[rings[0]].mean(axis=0)),
        edge_ratio=round(float(np.median(lum[rings[0]])) / max(ref, 1e-3), 3),
        lum=round(ref, 3),
        sat=round(float(np.median(saturation(rgb[interior]))), 3),
        lum_range=round(float(np.percentile(in_lum, 90) - np.percentile(in_lum, 10)), 3),
        palette=palette,
        coverage=round(float(mask.mean()), 3),
        bbox=[x0, y0, x1, y1],
        margin_px=margin,
        margin_rel=round(margin / max(w, h), 4),
        soft_edge=round(soft, 3),
    )
    return out


def expand(patterns: list[str]) -> list[str]:
    files: list[str] = []
    for p in patterns:
        hits = sorted(glob.glob(p, recursive=True))
        files.extend(hits or [p])
    return files


def summarize(reports: list[dict]) -> dict:
    ok = [r for r in reports if not r.get("empty")]
    s: dict = {"n": len(ok)}
    for k in KEYS:
        vals = [r[k] for r in ok]
        if vals:
            qs = statistics.quantiles(vals, n=10) if len(vals) > 1 else [vals[0]] * 9
            s[k] = {
                "p10": round(qs[0], 4),
                "median": round(statistics.median(vals), 4),
                "p90": round(qs[-1], 4),
            }
    sizes: dict[str, int] = {}
    for r in ok:
        key = "x".join(map(str, r["size"]))
        sizes[key] = sizes.get(key, 0) + 1
    s["sizes"] = dict(sorted(sizes.items(), key=lambda kv: -kv[1]))
    return s


CELL_KEYS = ("outline_cell", "lum", "sat", "lum_range", "coverage", "margin_cell", "edge_ratio")


def per_cell(r: dict, ppc: float) -> dict:
    """Add scale-free measures for a texture drawn at `ppc` texture pixels per map cell."""
    if not r.get("empty"):
        r["outline_cell"] = round(r["outline_px"] * 64 / ppc, 2)
        r["margin_cell"] = round(r["margin_px"] / ppc, 3)
    return r


def summarize_keys(reports: list[dict], keys: tuple[str, ...]) -> dict:
    ok = [r for r in reports if not r.get("empty")]
    s: dict = {"n": len(ok)}
    for k in keys:
        vals = [r[k] for r in ok if k in r]
        if vals:
            qs = statistics.quantiles(vals, n=10) if len(vals) > 1 else [vals[0]] * 9
            s[k] = {
                "p10": round(qs[0], 4),
                "median": round(statistics.median(vals), 4),
                "p90": round(qs[-1], 4),
            }
    return s


def compare(mine: dict, base: dict, keys: tuple[str, ...] = KEYS) -> list[str]:
    flags = []
    for k in keys:
        if k not in base or k not in mine:
            continue
        lo, hi = base[k]["p10"], base[k]["p90"]
        pad = (hi - lo) * 0.1 + 1e-4
        if not lo - pad <= mine[k] <= hi + pad:
            flags.append(f"{k}={mine[k]} outside reference p10-p90 [{lo}, {hi}]")
    return flags


def fmt(r: dict) -> str:
    if r.get("empty"):
        return f"{r['file']}: (no opaque pixels)"
    pal = " ".join(f"{c}:{int(s * 100)}%" for c, s in r["palette"])
    return (
        f"{r['file']}  {r['size'][0]}x{r['size'][1]}\n"
        f"  outline {r['outline_px']}px ({r['outline_rel']:.3f} of size) {r['outline_rgb']}"
        f"  edge_ratio {r['edge_ratio']}  soft_edge {r['soft_edge']}\n"
        f"  lum {r['lum']}  sat {r['sat']}  lum_range {r['lum_range']}\n"
        f"  coverage {r['coverage']}  bbox {r['bbox']}  margin {r['margin_px']}px\n"
        f"  palette {pal}"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--summary", action="store_true", help="medians/percentiles over all files")
    ap.add_argument("--against", metavar="GLOB", help="compare each file to these references")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--ppc", type=float, help="texture px per map cell of FILES (e.g. 128)")
    ap.add_argument("--ref-ppc", type=float, help="px per cell of --against refs (default 64)")
    a = ap.parse_args(argv)
    reports = [analyze(f) for f in expand(a.files)]
    keys = KEYS
    if a.ppc or a.ref_ppc:
        keys = CELL_KEYS
        reports = [per_cell(r, a.ppc or 64) for r in reports]
    if a.against:
        refs = [analyze(f) for f in expand([a.against])]
        if keys is CELL_KEYS:
            refs = [per_cell(r, a.ref_ppc or 64) for r in refs]
        base = summarize_keys(refs, keys) if keys is CELL_KEYS else summarize(refs)
        result = [{"file": r["file"], "flags": compare(r, base, keys)} for r in reports]
        if a.json:
            print(json.dumps({"reference": base, "results": result, "reports": reports}, indent=1))
        else:
            print(
                f"reference: {base['n']} sprites, "
                + ", ".join(f"{k} {base[k]['median']}" for k in keys if k in base)
            )
            for r, res in zip(reports, result):
                print(fmt(r))
                if "outline_cell" in r:
                    print(
                        f"  per cell: outline {r['outline_cell']} px@64  margin "
                        f"{r['margin_cell']} cells"
                    )
                for f in res["flags"]:
                    print(f"  ! {f}")
                if not res["flags"]:
                    print("  ok: inside the reference range on every measure")
        return 0
    if a.summary:
        s = summarize(reports)
        print(json.dumps(s, indent=1))
        return 0
    if a.json:
        print(json.dumps(reports, indent=1))
    else:
        print("\n".join(fmt(r) for r in reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
