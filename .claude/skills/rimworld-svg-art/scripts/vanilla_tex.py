# /// script
# requires-python = ">=3.11"
# dependencies = ["UnityPy>=1.20", "Pillow>=10"]
# ///
"""Find and extract vanilla RimWorld textures (Core + DLC) as PNGs, for reference only.

    uv run vanilla_tex.py --search 'things/item/.*/(steel|gold)'   # list matches (regex)
    uv run vanilla_tex.py --extract 'weapon/.*rifle' [--limit 40]   # write PNGs to the cache
    uv run vanilla_tex.py --extract ... --out DIR                   # somewhere else (not a mod!)
    uv run vanilla_tex.py --stats [PREFIX]                          # counts + typical sizes
    uv run vanilla_tex.py --overrides 'eggbox|furniture/bed/'      # installed mods that
                                                                    # replace these textures
    uv run vanilla_tex.py --path                                    # print the cache dir

Core textures live in `RimWorldWin64_Data/resources.assets` (paths come from the
ResourceManager in `globalgamemanagers`); DLC textures in `Data/<DLC>/AssetBundles/resources_*`.
Paths are normalised to the texPath form mods use, lower-cased and prefixed by the source:
`core:things/item/resource/steel/steel_a`, `biotech:things/pawn/mechanoid/...`.

The first run builds `.cache/textures/index-<game version>.json` (~30 s). Extracted PNGs go to
`.cache/textures/png/<source>/<path>.png`. The cache is gitignored: this is Ludeon's art — study
it, measure it, never copy it into a mod or commit it.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[2]
GAME = REPO / "links" / "game"
CACHE = SKILL / ".cache" / "textures"
DATA = GAME / "RimWorldWin64_Data"
DLCS = ("Royalty", "Ideology", "Biotech", "Anomaly", "Odyssey")


def game_version() -> str:
    try:
        return (GAME / "Version.txt").read_text().split()[0]
    except OSError:
        return "unknown"


def norm_bundle_path(p: str) -> str | None:
    """'assets/data/biotech/textures/things/x.png' -> 'things/x' (None if not a texture path)."""
    m = re.match(r"assets/data/[^/]+/textures/(.+?)(?:\.\w+)?$", p)
    return m.group(1) if m else None


def norm_core_path(p: str) -> str | None:
    """'textures/things/item/x' -> 'things/item/x' (None if not under textures/)."""
    return p[len("textures/") :] if p.startswith("textures/") else None


def build_index() -> list[dict]:
    import UnityPy

    entries: list[dict] = []
    ggm = UnityPy.load(str(DATA / "globalgamemanagers"))
    sf = next(iter(ggm.files.values()))
    ext = {i + 1: e.path for i, e in enumerate(sf.externals)}
    rm = next(o for o in ggm.objects if o.type.name == "ResourceManager").read()
    res_id = next(i for i, p in ext.items() if p.endswith("resources.assets"))
    core = UnityPy.load(str(DATA / "resources.assets"))
    objs = {o.path_id: o for o in core.objects}
    for path, ptr in rm.m_Container:
        o = objs.get(ptr.m_PathID) if ptr.m_FileID == res_id else None
        tp = norm_core_path(path)
        if o is None or tp is None or o.type.name != "Texture2D":
            continue
        t = o.read()
        entries.append(
            {
                "src": "core",
                "path": tp,
                "file": "resources.assets",
                "id": ptr.m_PathID,
                "w": t.m_Width,
                "h": t.m_Height,
            }
        )
    for dlc in DLCS:
        bundle = GAME / "Data" / dlc / "AssetBundles" / f"resources_{dlc.lower()}"
        if not bundle.exists():
            continue
        env = UnityPy.load(str(bundle))
        for path, o in env.container.items():
            tp = norm_bundle_path(path)
            if tp is None or o.type.name != "Texture2D":
                continue
            t = o.read()
            entries.append(
                {
                    "src": dlc.lower(),
                    "path": tp,
                    "file": str(bundle.relative_to(GAME)),
                    "id": o.path_id,
                    "w": t.m_Width,
                    "h": t.m_Height,
                }
            )
    return entries


def load_index(rebuild: bool = False) -> list[dict]:
    f = CACHE / f"index-{game_version()}.json"
    if f.exists() and not rebuild:
        return json.loads(f.read_text())
    print("indexing game textures (one-time, ~30 s)...", file=sys.stderr)
    entries = build_index()
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(entries))
    return entries


def key(e: dict) -> str:
    return f"{e['src']}:{e['path']}"


def search(entries: list[dict], pattern: str) -> list[dict]:
    rx = re.compile(pattern, re.IGNORECASE)
    return sorted((e for e in entries if rx.search(key(e))), key=key)


def extract(hits: list[dict], out: Path) -> list[Path]:
    import UnityPy

    by_file: dict[str, list[dict]] = collections.defaultdict(list)
    for e in hits:
        by_file[e["file"]].append(e)
    written = []
    for file, es in by_file.items():
        src = DATA / file if file == "resources.assets" else GAME / file
        env = UnityPy.load(str(src))
        objs = {o.path_id: o for o in env.objects}
        for e in es:
            dest = out / e["src"] / (e["path"] + ".png")
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                objs[e["id"]].read().image.save(dest)
            written.append(dest)
    return written


def mod_roots() -> list[Path]:
    roots = []
    for base in (REPO / "links" / "mods", REPO / "links" / "workshop"):
        if base.exists():
            roots.extend(d for d in base.iterdir() if d.is_dir())
    return roots


def mod_name(root: Path) -> str:
    about = root / "About" / "About.xml"
    try:
        m = re.search(r"<name>(.*?)</name>", about.read_text(encoding="utf-8", errors="replace"))
        return m.group(1).strip() if m else root.name
    except OSError:
        return root.name


def active_ids() -> set[str]:
    cfg = REPO / "links" / "config" / "ModsConfig.xml"
    try:
        text = cfg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    block = re.search(r"<activeMods>(.*?)</activeMods>", text, re.DOTALL)
    return (
        {x.strip().lower() for x in re.findall(r"<li>(.*?)</li>", block.group(1))}
        if block
        else set()
    )


def package_id(root: Path) -> str:
    about = root / "About" / "About.xml"
    try:
        m = re.search(
            r"<packageId>(.*?)</packageId>", about.read_text(encoding="utf-8", errors="replace")
        )
        return m.group(1).strip().lower() if m else ""
    except OSError:
        return ""


def overrides(entries: list[dict], pattern: str) -> list[tuple[str, str, bool, str]]:
    """(vanilla key, mod name, active, file) for mod textures at the same path as a vanilla one.
    Texture-replacement mods (upscales, retextures) change what the user calls "vanilla"."""
    wanted = {e["path"]: key(e) for e in search(entries, pattern)}
    if not wanted:
        return []
    active = active_ids()
    out = []
    for root in mod_roots():
        for f in root.rglob("*"):
            if f.suffix.lower() not in (".png", ".dds", ".jpg", ".jpeg", ".psd"):
                continue
            parts = [x.lower() for x in f.relative_to(root).parts]
            if "textures" not in parts:
                continue
            rel = "/".join(parts[parts.index("textures") + 1 :])
            rel = rel.rsplit(".", 1)[0]
            if rel in wanted:
                out.append((wanted[rel], mod_name(root), package_id(root) in active, str(f)))
    return sorted(out)


def stats(entries: list[dict], prefix: str, depth: int) -> None:
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for e in entries:
        if e["path"].startswith(prefix):
            parts = e["path"].split("/")
            groups["/".join(parts[:depth])].append(e)
    for g, es in sorted(groups.items()):
        sizes = collections.Counter(f"{e['w']}x{e['h']}" for e in es)
        common = ", ".join(f"{s} ({n})" for s, n in sizes.most_common(3))
        print(f"{len(es):5}  {g:45}  {common}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--search", metavar="REGEX")
    ap.add_argument("--extract", metavar="REGEX")
    ap.add_argument("--stats", nargs="?", const="", metavar="PREFIX")
    ap.add_argument("--depth", type=int, default=3, help="--stats grouping depth (default 3)")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", type=Path, default=CACHE / "png")
    ap.add_argument("--rebuild", action="store_true", help="re-index the game files")
    ap.add_argument("--overrides", metavar="REGEX", help="installed mods replacing these")
    ap.add_argument("--path", action="store_true")
    a = ap.parse_args(argv)
    if a.path:
        print(CACHE)
        return 0
    entries = load_index(a.rebuild)
    if a.overrides:
        rows = overrides(entries, a.overrides)
        for k, name, act, f in rows:
            print(f"{k:55} {'ACTIVE ' if act else 'inactive'} {name}\n    {f}")
        if not rows:
            print("no installed mod replaces these textures")
        return 0
    if a.stats is not None:
        stats(entries, a.stats, a.depth)
        return 0
    pattern = a.search or a.extract
    if not pattern:
        ap.print_help()
        return 2
    hits = search(entries, pattern)
    shown = hits[: a.limit]
    if a.extract:
        for p in extract(shown, a.out):
            print(p)
    else:
        for e in shown:
            print(f"{key(e):70} {e['w']}x{e['h']}")
    if len(hits) > len(shown):
        print(f"... {len(hits) - len(shown)} more (--limit)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
