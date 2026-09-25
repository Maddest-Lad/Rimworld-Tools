"""Offline emulation of RimWorld 1.6 PatchOperations (Verse.PatchOperation*), for patch_check.py.

Semantics follow the decompiled game: an operation "fails" when its worker returns false, after
`<success>` (Normal | Invert | Always | Never) is applied; the game then logs
`[<mod>] Patch operation <op> failed`. Sequences stop at the first failing child. `li` children of
`<operations>` honour MayRequire / MayRequireAnyOf; a MayRequire on a top-level `<Operation>` is
ignored by the game (the op still runs), which is reported as a warning.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from rwxml import DefDocument, Mod, norm_id, parse_file, xml_files

KNOWN = {
    "PatchOperationAdd",
    "PatchOperationInsert",
    "PatchOperationRemove",
    "PatchOperationReplace",
    "PatchOperationAttributeAdd",
    "PatchOperationAttributeSet",
    "PatchOperationAttributeRemove",
    "PatchOperationAddModExtension",
    "PatchOperationSetName",
    "PatchOperationSequence",
    "PatchOperationConditional",
    "PatchOperationFindMod",
    "PatchOperationTest",
}


ATTRIBUTE_OPS = {
    "PatchOperationAttributeAdd",
    "PatchOperationAttributeSet",
    "PatchOperationAttributeRemove",
}
READ_ONLY = {"PatchOperationConditional", "PatchOperationTest", *ATTRIBUTE_OPS}


def _depth(node: etree._Element) -> int:
    """0 = wrapper (document), 1 = <Defs>, 2 = a top-level def, 3+ = inside a def."""
    d = 0
    while (node := node.getparent()) is not None:
        d += 1
    return d


def _changes_index(short: str, node, op: etree._Element) -> bool:
    """Could this operation on `node` change which (type, defName) pairs exist?"""
    if not isinstance(node, etree._Element):  # text()/attribute result
        parent = node.getparent() if hasattr(node, "getparent") else None
        return parent is None or parent.tag == "defName"
    if node.tag == "defName":
        return True
    depth = _depth(node)
    if short in ("PatchOperationAdd", "PatchOperationAddModExtension"):
        adds_defname = op.find("value/defName") is not None
        return depth <= 1 or (depth == 2 and adds_defname)
    if short == "PatchOperationInsert":
        return depth <= 2
    return depth <= 2  # Remove / Replace / SetName of a whole def or of <Defs>


@dataclass
class OpResult:
    cls: str
    file: Path
    line: int | None
    xpath: str | None = None
    matched: int | None = None
    ok: bool = True
    note: str = ""
    children: list[OpResult] = field(default_factory=list)
    unsupported: bool = False

    def describe(self) -> str:
        bits = [self.cls.removeprefix("PatchOperation") or self.cls]
        if self.xpath:
            bits.append(self.xpath)
        if self.matched is not None:
            bits.append(f"-> {self.matched} node(s)")
        if self.note:
            bits.append(f"({self.note})")
        return " ".join(bits)


class PatchRunner:
    def __init__(self, doc: DefDocument, warnings: list[str] | None = None):
        self.doc = doc
        self.warnings = warnings if warnings is not None else []
        self.active_names = {m.name for m in doc.mods}
        self._op: etree._Element | None = None

    # -- helpers ------------------------------------------------------------------------

    def _select(self, xpath: str, res: OpResult) -> list:
        try:
            nodes = self.doc.select(xpath)
        except etree.XPathError as exc:
            res.note = f"invalid XPath: {exc}"
            res.matched = 0
            return []
        if not isinstance(nodes, list):  # boolean / number / string expression
            res.note = f"XPath returns {type(nodes).__name__}, not nodes"
            res.matched = 0
            return []
        res.matched = len(nodes)
        short = res.cls.split(".")[-1]
        if short not in READ_ONLY and any(_changes_index(short, n, self._op) for n in nodes):
            self.doc.invalidate()
        return nodes

    @staticmethod
    def _value_children(op: etree._Element) -> list:
        value = op.find("value")
        if value is None:
            return []
        items = []
        if value.text and value.text.strip():
            items.append(value.text)
        for c in value:
            items.append(c)
            if c.tail and c.tail.strip():
                items.append(c.tail)
        return items

    @staticmethod
    def _append(target: etree._Element, item) -> None:
        if isinstance(item, str):
            if len(target):
                target[-1].tail = (target[-1].tail or "") + item
            else:
                target.text = (target.text or "") + item
        else:
            target.append(copy.deepcopy(item))

    @staticmethod
    def _field(op: etree._Element, name: str) -> str | None:
        v = op.findtext(name)
        return v.strip() if v is not None else None

    # -- dispatch -----------------------------------------------------------------------

    def run(self, op: etree._Element, file: Path) -> OpResult:
        cls = (op.get("Class") or "").strip()
        res = OpResult(cls or "<no Class>", file, op.sourceline, self._field(op, "xpath"))
        short = cls.split(".")[-1]
        if short not in KNOWN:
            res.unsupported = True
            res.note = "custom operation class - not evaluated (needs its mod's assembly)"
            return res
        worker = getattr(self, "_op_" + short.removeprefix("PatchOperation").lower())
        outer, self._op = self._op, op
        try:
            ok = worker(op, res)
        finally:
            self._op = outer
        success = self._field(op, "success") or "Normal"
        if success == "Always":
            ok = True
        elif success == "Never":
            ok = False
        elif success == "Invert":
            ok = not ok
        if success != "Normal":
            res.note = (res.note + "; " if res.note else "") + f"success={success}"
        res.ok = ok
        return res

    def _need_xpath(self, res: OpResult) -> bool:
        if not res.xpath:
            res.note = "missing <xpath>"
            return False
        return True

    # -- node operations ----------------------------------------------------------------

    def _op_add(self, op, res):
        if not self._need_xpath(res):
            return False
        nodes = self._select(res.xpath, res)
        items = self._value_children(op)
        prepend = self._field(op, "order") == "Prepend"
        for n in nodes:
            if not isinstance(n, etree._Element):
                continue
            if prepend:
                for item in reversed(items):
                    if isinstance(item, str):
                        n.text = item + (n.text or "")
                    else:
                        c = copy.deepcopy(item)
                        c.tail = n.text
                        n.text = None
                        n.insert(0, c)
            else:
                for item in items:
                    self._append(n, item)
        return bool(nodes)

    def _op_insert(self, op, res):
        if not self._need_xpath(res):
            return False
        nodes = self._select(res.xpath, res)
        items = [i for i in self._value_children(op) if not isinstance(i, str)]
        append = self._field(op, "order") == "Append"
        for n in nodes:
            if not isinstance(n, etree._Element) or n.getparent() is None:
                continue
            if append:
                for item in reversed(items):  # InsertAfter each → keeps given order
                    n.addnext(copy.deepcopy(item))
            else:
                for item in items:
                    n.addprevious(copy.deepcopy(item))
        return bool(nodes)

    def _op_remove(self, op, res):
        if not self._need_xpath(res):
            return False
        nodes = self._select(res.xpath, res)
        for n in nodes:
            if isinstance(n, etree._Element) and n.getparent() is not None:
                self.doc.origins.pop(n, None)
                n.getparent().remove(n)
            elif hasattr(n, "getparent") and getattr(n, "is_text", False):
                n.getparent().text = None
        return bool(nodes)

    def _op_replace(self, op, res):
        if not self._need_xpath(res):
            return False
        nodes = self._select(res.xpath, res)
        items = self._value_children(op)
        for n in nodes:
            if isinstance(n, etree._Element) and n.getparent() is not None:
                origin = self.doc.origins.pop(n, None)
                for item in items:
                    if isinstance(item, str):
                        continue
                    new = copy.deepcopy(item)
                    n.addprevious(new)
                    if origin is not None:
                        self.doc.origins[new] = origin
                n.getparent().remove(n)
            elif getattr(n, "is_text", False):  # …/text()
                n.getparent().text = "".join(
                    i if isinstance(i, str) else etree.tostring(i, encoding=str) for i in items
                )
        return bool(nodes)

    def _op_setname(self, op, res):
        if not self._need_xpath(res):
            return False
        name = self._field(op, "name")
        nodes = self._select(res.xpath, res)
        for n in nodes:
            if isinstance(n, etree._Element) and name:
                n.tag = name
                n.attrib.clear()  # the game builds a fresh element: attributes are dropped
        return bool(nodes)

    def _op_addmodextension(self, op, res):
        if not self._need_xpath(res):
            return False
        nodes = self._select(res.xpath, res)
        items = [i for i in self._value_children(op) if not isinstance(i, str)]
        for n in nodes:
            ext = n.find("modExtensions")
            if ext is None:
                ext = etree.SubElement(n, "modExtensions")
            for item in items:
                ext.append(copy.deepcopy(item))
        return bool(nodes)

    # -- attributes ---------------------------------------------------------------------

    def _attr_nodes(self, op, res):
        if not self._need_xpath(res):
            return None, []
        attr = self._field(op, "attribute")
        if not attr:
            res.note = "missing <attribute>"
        return attr, [n for n in self._select(res.xpath, res) if isinstance(n, etree._Element)]

    def _op_attributeadd(self, op, res):
        attr, nodes = self._attr_nodes(op, res)
        ok = False
        for n in nodes:
            if attr and n.get(attr) is None:
                n.set(attr, self._field(op, "value") or "")
                ok = True
        if nodes and not ok:
            res.note = f"attribute {attr} already present on every match"
        return ok

    def _op_attributeset(self, op, res):
        attr, nodes = self._attr_nodes(op, res)
        for n in nodes:
            if attr:
                n.set(attr, self._field(op, "value") or "")
        return bool(nodes)

    def _op_attributeremove(self, op, res):
        attr, nodes = self._attr_nodes(op, res)
        ok = False
        for n in nodes:
            if attr and n.get(attr) is not None:
                del n.attrib[attr]
                ok = True
        if nodes and not ok:
            res.note = f"attribute {attr} absent on every match"
        return ok

    # -- control flow -------------------------------------------------------------------

    def _child(self, op, name, res) -> OpResult | None:
        node = op.find(name)
        if node is None:
            return None
        child = self.run(node, res.file)
        child.note = f"{name}: " + child.note if child.note else name
        res.children.append(child)
        return child

    def _op_test(self, op, res):
        if not self._need_xpath(res):
            return False
        res.note = "PatchOperationTest is obsolete; use PatchOperationConditional"
        return bool(self._select(res.xpath, res))

    def _op_conditional(self, op, res):
        if not self._need_xpath(res):
            return False
        found = bool(self._select(res.xpath, res))
        has_match, has_nomatch = op.find("match") is not None, op.find("nomatch") is not None
        if found and has_match:
            return self._child(op, "match", res).ok
        if not found and has_nomatch:
            return self._child(op, "nomatch", res).ok
        return True if has_match else has_nomatch

    def _op_findmod(self, op, res):
        mods = [li.text.strip() for li in op.findall("mods/li") if li.text]
        res.xpath = None
        hit = next((m for m in mods if m in self.active_names), None)
        res.note = (f"found {hit!r}" if hit else f"none of {mods} loaded") + " (matches mod NAME)"
        ids_by_mistake = [
            m
            for m in mods
            if "." in m and m not in self.active_names and norm_id(m) in self.doc.active
        ]
        if ids_by_mistake:
            self.warnings.append(
                f"{res.file}:{res.line}: FindMod lists packageId(s) {ids_by_mistake}; it compares "
                "mod names — use the <name> from About.xml, or MayRequire / LoadFolders instead"
            )
        if hit and op.find("match") is not None:
            return self._child(op, "match", res).ok
        if not hit and op.find("nomatch") is not None:
            return self._child(op, "nomatch", res).ok
        return True

    def _op_sequence(self, op, res):
        ops = op.find("operations")
        if ops is None:
            res.note = "missing <operations>"
            return False
        for li in ops:
            if not isinstance(li.tag, str):
                continue
            need_all = li.get("MayRequire")
            need_any = li.get("MayRequireAnyOf")
            if need_all and not all(norm_id(p) in self.doc.active for p in need_all.split(",")):
                res.children.append(
                    OpResult(
                        li.get("Class") or "li",
                        res.file,
                        li.sourceline,
                        note=f"skipped: MayRequire {need_all}",
                    )
                )
                continue
            if need_any and not any(norm_id(p) in self.doc.active for p in need_any.split(",")):
                res.children.append(
                    OpResult(
                        li.get("Class") or "li",
                        res.file,
                        li.sourceline,
                        note=f"skipped: MayRequireAnyOf {need_any}",
                    )
                )
                continue
            child = self.run(li, res.file)
            res.children.append(child)
            if not child.ok:
                res.note = f"stopped at line {child.line}"
                return False
        return True


def load_operations(
    mod: Mod, active: set[str], errors: list[str], warnings: list[str]
) -> list[tuple[Path, etree._Element]]:
    """ModContentPack.LoadPatches: root must be <Patch>, children must be <Operation>."""
    out = []
    for f in xml_files(mod, "Patches", active):
        root = parse_file(f, errors)
        if root is None:
            continue
        if root.tag != "Patch":
            errors.append(
                f"{f}: unexpected document element {root.tag}, expected 'Patch' " "(file skipped)"
            )
            continue
        for child in root:
            if not isinstance(child.tag, str):
                continue
            if child.tag != "Operation":
                errors.append(
                    f"{f}:{child.sourceline}: unexpected element {child.tag}, "
                    "expected 'Operation' (skipped)"
                )
                continue
            if child.get("MayRequire") or child.get("MayRequireAnyOf"):
                warnings.append(
                    f"{f}:{child.sourceline}: MayRequire on a top-level <Operation> "
                    "is ignored by the game - wrap it in a Sequence li, use "
                    "FindMod/Conditional, or a LoadFolders IfModActive folder"
                )
            out.append((f, child))
    return out


def run_all(
    doc: DefDocument,
    mods: list[Mod],
    errors: list[str],
    warnings: list[str],
    report_for: set[str] | None = None,
) -> list[tuple[Mod, OpResult]]:
    """Apply every mod's patches in load order; return results for mods in `report_for`."""
    runner = PatchRunner(doc, warnings)
    results = []
    for mod in mods:
        own_errors: list[str] = []
        ops = load_operations(
            mod,
            doc.active,
            own_errors,
            warnings if report_for is None or mod.key in report_for else [],
        )
        if report_for is None or mod.key in report_for:
            errors.extend(own_errors)
        for f, op in ops:
            res = runner.run(op, f)
            if report_for is None or mod.key in report_for:
                results.append((mod, res))
    return results
