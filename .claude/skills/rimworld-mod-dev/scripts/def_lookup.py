"""Find defs and vanilla precedent in the installed game (and optionally mods). Read-only.

    python def_lookup.py NAME [--type T] [--resolved] [--patched]   # a defName or Name="…"
    python def_lookup.py --grep REGEX [--type T]                    # defNames/Names matching
    python def_lookup.py --uses TAG [--type T]                      # defs containing <TAG>
    python def_lookup.py --class CLASS                              # Class="…"/…Class>CLASS<
    python def_lookup.py --xpath 'Defs/ThingDef[comps/li/@Class="CompProperties_Glower"]'

Loads official Core + DLC content; `--active` loads the whole ModsConfig.xml active list,
`--with MOD` adds a mod directory / packageId / name. `--patched` runs every loaded mod's
patches first (what the game sees before inheritance). `--resolved` prints the def after
Name/ParentName inheritance, exactly as XmlInheritance merges it. Output lists each hit as
`Type defName [Name/ParentName]  Mod/relative/file.xml:line`.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lxml import etree
from rwxml import (
    Inheritance,
    build_document,
    default_mods,
    installed_mods,
    iter_defs,
    label,
    resolve_mod,
)


def top_level(node):
    while node is not None and node.getparent() is not None and node.getparent().tag != "Defs":
        node = node.getparent()
    return node


def show(doc, node) -> str:
    o = doc.origin(node)
    return f"{label(node)}  {o.where(node) if o else '(added by a patch)'}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("name", nargs="?", help="exact defName or Name attribute")
    ap.add_argument("--type", help="def type (element name), e.g. ThingDef, HediffDef")
    ap.add_argument("--grep", help="regex over defName / Name")
    ap.add_argument("--uses", metavar="TAG", help="defs that contain an element <TAG>")
    ap.add_argument(
        "--class",
        dest="cls",
        metavar="CLASS",
        help='defs using CLASS as Class="…" or as a …Class element value',
    )
    ap.add_argument("--xpath", help="raw XPath over the unified document; prints owning defs")
    ap.add_argument("--resolved", action="store_true", help="print the def after inheritance")
    ap.add_argument("--raw", action="store_true", help="print the def as written")
    ap.add_argument("--patched", action="store_true", help="apply all loaded patches first")
    ap.add_argument("--active", action="store_true", help="load the ModsConfig.xml active list")
    ap.add_argument("--with", dest="extra", action="append", default=[], metavar="MOD")
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args(argv)
    if not any((args.name, args.grep, args.uses, args.cls, args.xpath)):
        ap.error("give NAME or one of --grep / --uses / --class / --xpath")

    installed = installed_mods() if args.extra or args.active else {}
    extras = [resolve_mod(e, installed) for e in args.extra]
    mods, active = default_mods(extras, with_active=args.active)
    doc = build_document(mods, active)
    if args.patched:
        from patchops import run_all

        run_all(doc, mods, [], [], report_for=set())
    inh = Inheritance(doc)
    defs = list(iter_defs(doc, args.type))
    print(
        f"[{len(mods)} mod(s) loaded, {len(defs)} {args.type or 'top-level'} node(s)"
        f"{', patched' if args.patched else ''}]"
    )

    hits: list = []
    if args.name:
        hits = [
            n
            for n in defs
            if (n.findtext("defName") or "").strip() == args.name or n.get("Name") == args.name
        ]
        if not hits:
            low = args.name.lower()
            near = [
                n
                for n in defs
                if low in (n.findtext("defName") or "").lower()
                or low in (n.get("Name") or "").lower()
            ]
            print(
                f"no exact match for {args.name!r}" + (f"; similar ({len(near)}):" if near else "")
            )
            for n in near[: args.limit]:
                print("  " + show(doc, n))
            return 1
    elif args.grep:
        rx = re.compile(args.grep, re.IGNORECASE)
        hits = [
            n
            for n in defs
            if rx.search(n.findtext("defName") or "") or rx.search(n.get("Name") or "")
        ]
    elif args.uses:
        hits = [n for n in defs if n.find(f".//{args.uses}") is not None or n.tag == args.uses]
    elif args.cls:
        c = args.cls
        hits = [
            n
            for n in defs
            if n.xpath(
                f'.//@Class[.="{c}" or substring(., string-length(.) - {len(c)}) = ".{c}"] | '
                f'.//*[substring(name(), string-length(name()) - 4) = "Class" and '
                f'(normalize-space(text()) = "{c}" or substring(normalize-space(text()), '
                f'string-length(normalize-space(text())) - {len(c)}) = ".{c}")]'
            )
        ]
    elif args.xpath:
        found = doc.select(args.xpath)
        if not isinstance(found, list):
            print(found)
            return 0
        seen: dict[int, object] = {}
        for f in found:
            el = f if isinstance(f, etree._Element) else f.getparent()
            top = top_level(el)
            if top is not None and (args.type is None or top.tag == args.type):
                seen.setdefault(id(top), top)
        hits = list(seen.values())
        print(f"{len(found)} XPath result(s) in {len(hits)} def(s)")

    by_mod = Counter((doc.origin(n).mod.name if doc.origin(n) else "patch") for n in hits)
    if len(hits) > 1:
        print(f"{len(hits)} match(es): " + ", ".join(f"{m} {k}" for m, k in by_mod.most_common()))
    for n in hits[: args.limit]:
        print(show(doc, n))
        if args.name or len(hits) == 1:
            for parent in inh.chain(n)[1:]:
                print("  <- " + show(doc, parent))
            if n.get("ParentName") and inh.parent_of(n) is None:
                print(f'  <- MISSING parent Name="{n.get("ParentName")}"')
        if args.raw:
            print(etree.tostring(n, encoding=str).rstrip())
        if args.resolved:
            resolved = inh.resolve(n)
            etree.indent(resolved, space="  ")
            print(etree.tostring(resolved, encoding=str).rstrip())
    if len(hits) > args.limit:
        print(f"... {len(hits) - args.limit} more (--limit)")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
