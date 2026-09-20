from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from toposort import CircularDependencyError, toposort

from . import db
from .mods import AboutXml

# Hard-pinned tiers. These encode real modding knowledge that exists in no file format.
TIER_ZERO: frozenset[str] = frozenset(
    {
        "zetrith.prepatcher",
        "brrainz.harmony",
        "brrainz.visualexceptions",
        "ludeon.rimworld",
        "ludeon.rimworld.royalty",
        "ludeon.rimworld.ideology",
        "ludeon.rimworld.biotech",
        "ludeon.rimworld.anomaly",
        "ludeon.rimworld.odyssey",
    }
)
TIER_ONE: frozenset[str] = frozenset(
    {
        "adaptive.storage.framework",
        "aoba.framework",
        "aoba.exosuit.framework",
        "ebsg.framework",
        "imranfish.xmlextensions",
        "thesepeople.ritualattachableoutcomes",
        "ohno.asf.ab.local",
        "oskarpotocki.vanillafactionsexpanded.core",
        "owlchemist.cherrypicker",
        "redmattis.betterprerequisites",
        "smashphil.vehicleframework",
        "unlimitedhugs.hugslib",
        "vanillaexpanded.backgrounds",
    }
)

_MAX_CYCLES_REPORTED = 20


@dataclass
class Compiled:
    """`after -> {before -> {sources}}`: `after` must load after every `before`.

    Provenance is kept per edge so a cycle can name the rule that created each link.
    """

    edges: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    tier_one: set[str] = field(default_factory=set)
    tier_three: set[str] = field(default_factory=set)
    incompatible: dict[str, set[str]] = field(default_factory=dict)
    removed: list[dict[str, str]] = field(default_factory=list)

    def add(self, after: str, before: str, source: str) -> None:
        if after == before:
            return
        self.edges.setdefault(after, {}).setdefault(before, set()).add(source)

    def remove(self, after: str, before: str, source: str) -> None:
        dropped = self.edges.get(after, {}).pop(before, None)
        if dropped:
            self.removed.append(
                {"after": after, "before": before, "by": source, "was": sorted(dropped)}
            )


def compile_rules(
    abouts: Mapping[str, AboutXml],
    community: Mapping[str, db.Rule] | None,
    user: Mapping[str, db.Rule] | None,
) -> Compiled:
    """Union About < Community < User, exactly as RimSort does — then apply user removals.

    Edges to packageIds that aren't installed are dropped; "missing" is a separate check.
    """
    installed = set(abouts)
    c = Compiled()
    for pid, about in abouts.items():
        for other in about.load_after:
            if other in installed:
                c.add(pid, other, f"about:{pid}")
        for other in about.load_before:
            if other in installed:
                c.add(other, pid, f"about:{pid}")
        for other in about.incompatible_with:
            c.incompatible.setdefault(pid, set()).add(other)
            c.incompatible.setdefault(other, set()).add(pid)

    for layer, rules in (("community", community), ("user", user)):
        for pid, rule in (rules or {}).items():
            if pid not in installed:
                continue
            for other in rule.load_after:
                if other in installed:
                    c.add(pid, other, layer)
            for other in rule.load_before:
                if other in installed:
                    c.add(other, pid, layer)
            if rule.load_top and pid not in TIER_ZERO:
                c.tier_one.add(pid)
            if rule.load_bottom:
                c.tier_three.add(pid)

    for pid, rule in (user or {}).items():
        for other in rule.remove_after:
            c.remove(pid, other, "user")
        for other in rule.remove_before:
            c.remove(other, pid, "user")
    return c


def _closure(start: Iterable[str], graph: Mapping[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(start)
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(graph.get(n, ()))
    return seen


@dataclass
class Cycle:
    members: list[str]
    edges: list[dict[str, Any]]  # {after, before, sources}


@dataclass
class SortResult:
    ok: bool
    order: list[str]
    tiers: dict[str, list[str]]
    cycles: list[Cycle]
    failed_tier: str | None = None


def sort(active: list[str], compiled: Compiled, names: Mapping[str, str]) -> SortResult:
    """Four-tier partition, each tier topologically sorted on its own, concatenated.

    Any cycle aborts the whole sort (safe: the caller writes nothing) and is returned as data.
    """
    active_set = set(active)
    deps: dict[str, set[str]] = {
        p: {d for d in compiled.edges.get(p, {}) if d in active_set} for p in active
    }
    rev: dict[str, set[str]] = {p: set() for p in active}
    for p, ds in deps.items():
        for d in ds:
            rev[d].add(p)

    t0 = _closure(TIER_ZERO & active_set, deps)
    t1 = _closure((TIER_ONE | compiled.tier_one) & active_set, deps) - t0
    t3 = _closure(compiled.tier_three & active_set, rev) - t0 - t1
    t2 = active_set - t0 - t1 - t3
    tiers = {"tier0": t0, "tier1": t1, "tier2": t2, "tier3": t3}

    def name_key(p: str) -> str:
        return (names.get(p) or p).lower()

    order: list[str] = []
    tier_lists: dict[str, list[str]] = {}
    for label, members in tiers.items():
        sub = {p: deps[p] & members for p in members}
        try:
            levels = list(toposort(sub))
        except CircularDependencyError:
            return SortResult(
                ok=False,
                order=[],
                tiers={k: sorted(v, key=name_key) for k, v in tiers.items()},
                cycles=find_cycles(sub, compiled),
                failed_tier=label,
            )
        placed = [p for level in levels for p in sorted(level, key=name_key)]
        tier_lists[label] = placed
        order.extend(placed)
    return SortResult(ok=True, order=list(dict.fromkeys(order)), tiers=tier_lists, cycles=[])


def find_cycles(sub: Mapping[str, set[str]], compiled: Compiled) -> list[Cycle]:
    g = nx.DiGraph()
    for after, befores in sub.items():
        for before in befores:
            g.add_edge(after, before)
    out: list[Cycle] = []
    for members in nx.simple_cycles(g):
        edges = []
        for i, after in enumerate(members):
            before = members[(i + 1) % len(members)]
            edges.append(
                {
                    "after": after,
                    "before": before,
                    "sources": sorted(compiled.edges.get(after, {}).get(before, set())),
                }
            )
        out.append(Cycle(members=list(members), edges=edges))
        if len(out) >= _MAX_CYCLES_REPORTED:
            break
    return out


def active_incompatibilities(active: Iterable[str], compiled: Compiled) -> list[tuple[str, str]]:
    """Declared-incompatible pairs that are both active. Not a sort concern; a validation one."""
    active_set = set(active)
    seen: set[tuple[str, str]] = set()
    for a in active_set:
        for b in compiled.incompatible.get(a, ()):
            if b in active_set:
                seen.add((min(a, b), max(a, b)))
    return sorted(seen)
