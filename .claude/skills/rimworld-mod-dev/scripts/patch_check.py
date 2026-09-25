"""Dry-run a mod's Patches and lint its Defs against the real 1.6 def tree. Never writes files.

    python patch_check.py MOD [--active] [--with MOD ...] [--json] [--verbose]

MOD is a mod directory (e.g. workspace/MyMod), a packageId or an installed mod name. The def
document is built like the game does: official Core + DLC content (or, with --active, the whole
active list from ModsConfig.xml in order) plus the target mod - which is appended if not already
in the list. All patches of every loaded mod run in load order; only the target mod's are
reported.

Reports per operation: class, xpath, matched node count, pass/FAIL (a FAIL is exactly what the
game logs as `[mod] Patch operation … failed`), Sequence children, MayRequire-skipped entries and
custom operation classes that cannot be evaluated offline. Then lints the target mod's own Defs:
XML syntax, root element, missing parents, duplicate Names/defNames/child nodes, invalid defNames,
empty or whitespace-padded descriptions, illegal label characters.

Exit code 1 when any operation fails or a lint error is found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lxml import etree
from patchops import OpResult, run_all
from rwxml import (
    Inheritance,
    Mod,
    build_document,
    default_mods,
    installed_mods,
    iter_defs,
    label,
    resolve_mod,
)

DEFNAME_RE = re.compile(r"^[a-zA-Z0-9\-_]*$")
LABEL_BAD_RE = re.compile(r"\[|\]|\{|\}")
SLOW_XPATH_RE = re.compile(r"(^|\|)\s*//|\[\s*//")


def lint_defs(doc, target: Mod, inh: Inheritance) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    mine = [n for n in iter_defs(doc) if (o := doc.origin(n)) and o.mod is target]
    seen_def: dict[tuple[str, str], str] = {}
    for n in iter_defs(doc):
        o = doc.origin(n)
        dn = (n.findtext("defName") or "").strip()
        if dn and o and o.mod is not target and (n.get("Abstract") or "").lower() != "true":
            seen_def.setdefault((n.tag, dn), o.mod.name)
    names = Counter(n.get("Name") for n in mine if n.get("Name"))
    for name, count in names.items():
        if count > 1:
            errors.append(f'Name="{name}" registered {count}x in this mod (XML error at load)')
    own_defnames: Counter = Counter()
    for n in mine:
        where = doc.origin(n).where(n)
        abstract = (n.get("Abstract") or "").lower() == "true"
        if n.get("ParentName") and inh.parent_of(n) is None:
            errors.append(
                f'{where}: {label(n)}: no parent named "{n.get("ParentName")}" '
                "is loaded before this mod"
            )
        dup = _duplicate_children(n)
        if dup:
            errors.append(f"{where}: {label(n)}: duplicate child node(s) {sorted(dup)}")
        if abstract:
            continue
        resolved = inh.resolve(n) if n.get("ParentName") else n
        dn = (resolved.findtext("defName") or "").strip()
        if not dn:
            errors.append(f"{where}: {label(n)}: no defName")
            continue
        if not DEFNAME_RE.match(dn):
            errors.append(f"{where}: defName {dn!r}: only letters, digits, _ and - allowed")
        own_defnames[(n.tag, dn)] += 1
        if (n.tag, dn) in seen_def:
            warnings.append(
                f"{where}: {n.tag} {dn} also defined by {seen_def[(n.tag, dn)]} - "
                "whichever loads later silently replaces the whole def; patch the original instead"
            )
        desc = resolved.findtext("description")
        if desc is not None and desc != desc.strip():
            warnings.append(f"{where}: {dn}: description has leading/trailing whitespace")
        lab = resolved.findtext("label")
        if lab and LABEL_BAD_RE.search(lab):
            warnings.append(f"{where}: {dn}: label contains [ ] {{ }} (grammar resolver)")
    for (tag, dn), count in own_defnames.items():
        if count > 1:
            errors.append(f"{tag} {dn} defined {count}x in this mod (game skips the extras)")
    return errors, warnings


def _duplicate_children(node: etree._Element, found: set | None = None) -> set:
    found = set() if found is None else found
    tags = Counter(c.tag for c in node if isinstance(c.tag, str) and c.tag != "li")
    found.update(t for t, k in tags.items() if k > 1)
    for c in node:
        if isinstance(c.tag, str):
            _duplicate_children(c, found)
    return found


def flatten(res: OpResult, depth: int = 0):
    yield depth, res
    for c in res.children:
        yield from flatten(c, depth + 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mod", help="mod directory, packageId or installed mod name")
    ap.add_argument(
        "--active",
        action="store_true",
        help="load the whole active list from ModsConfig.xml (slower, realistic)",
    )
    ap.add_argument(
        "--with",
        dest="extra",
        action="append",
        default=[],
        metavar="MOD",
        help="also load this mod before the target (repeatable)",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true", help="list passing operations too")
    args = ap.parse_args(argv)

    installed = installed_mods()
    target = resolve_mod(args.mod, installed)
    extras = [resolve_mod(e, installed) for e in args.extra]
    mods, active = default_mods([*extras, target], with_active=args.active)
    target = next(m for m in mods if m.key == target.key)
    doc = build_document(mods, active)
    load_errors = [e for e in doc.errors if str(target.root) in e]
    op_errors: list[str] = []
    warnings: list[str] = []
    results = run_all(doc, mods, op_errors, warnings, report_for={target.key})
    inh = Inheritance(doc)
    lint_err, lint_warn = lint_defs(doc, target, inh)
    for _, res in results:
        for _, r in flatten(res):
            if r.xpath and SLOW_XPATH_RE.search(r.xpath):
                warnings.append(
                    f"{r.file}:{r.line}: xpath starts with // (scans every node); "
                    'prefer Defs/ThingDef[defName="X"]/...'
                )

    failed = [r for _, r in results if not r.ok]
    unsupported = [r for _, res in results for _, r in flatten(res) if r.unsupported]
    errors = load_errors + op_errors + lint_err
    if args.json:

        def enc(r: OpResult):
            return {
                "class": r.cls,
                "file": str(r.file),
                "line": r.line,
                "xpath": r.xpath,
                "matched": r.matched,
                "ok": r.ok,
                "note": r.note,
                "children": [enc(c) for c in r.children],
            }

        print(
            json.dumps(
                {
                    "mod": str(target),
                    "loaded_mods": len(mods),
                    "operations": len(results),
                    "failed": len(failed),
                    "results": [enc(r) for _, r in results],
                    "errors": errors,
                    "warnings": warnings + lint_warn,
                    "unsupported": len(unsupported),
                },
                indent=2,
            )
        )
    else:
        print(
            f"{target} - {len(results)} top-level operation(s), {len(failed)} failed; "
            f"def tree: {len(mods)} mod(s){' (active list)' if args.active else ''}"
        )
        for _, res in results:
            if res.ok and not args.verbose and not any(not c.ok for _, c in flatten(res)):
                continue
            for depth, r in flatten(res):
                mark = "SKIP" if r.unsupported else ("ok  " if r.ok else "FAIL")
                rel = r.file.name
                print(f"  {'  ' * depth}{mark} {rel}:{r.line} {r.describe()}")
        for title, items in (("errors", errors), ("warnings", warnings + lint_warn)):
            if items:
                print(f"{title} ({len(items)}):")
                for i in items:
                    print(f"  - {i}")
        if unsupported:
            print(
                f"{len(unsupported)} custom operation(s) not evaluated; their effects are "
                "missing from the tree"
            )
        if not failed and not errors:
            print("no failing operations, no lint errors")
    return 1 if failed or errors else 0


if __name__ == "__main__":
    sys.exit(main())
