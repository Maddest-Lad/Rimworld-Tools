from __future__ import annotations

from src.rimworld_tools import db, sorting
from src.rimworld_tools.mods import AboutXml, PackageId


def about(
    pid: str, after: list[str] = (), before: list[str] = (), incompat: list[str] = ()
) -> AboutXml:
    return AboutXml(
        package_id=PackageId(pid),
        name=pid.split(".")[-1].title(),
        load_after=[PackageId(x) for x in after],
        load_before=[PackageId(x) for x in before],
        incompatible_with=[PackageId(x) for x in incompat],
    )


def world(*abouts: AboutXml) -> dict[str, AboutXml]:
    return {a.package_id: a for a in abouts}  # type: ignore[misc]


def names(abouts: dict[str, AboutXml]) -> dict[str, str]:
    return {p: a.name or p for p, a in abouts.items()}


CORE = "ludeon.rimworld"
HARMONY = "brrainz.harmony"
HUGS = "unlimitedhugs.hugslib"


class TestCompile:
    def test_union_across_layers_with_provenance(self) -> None:
        w = world(about("a.x", after=["b.y"]), about("b.y"), about("c.z"))
        community = {"a.x": db.Rule(load_after={"c.z"})}
        user = {"c.z": db.Rule(load_before={"b.y"})}
        c = sorting.compile_rules(w, community, user)
        assert c.edges["a.x"]["b.y"] == {"about:a.x"}
        assert c.edges["a.x"]["c.z"] == {"community"}
        assert c.edges["b.y"]["c.z"] == {"user"}  # loadBefore inverts direction

    def test_edges_to_uninstalled_dropped_and_self_loops_ignored(self) -> None:
        w = world(about("a.x", after=["ghost.mod", "a.x"]))
        c = sorting.compile_rules(w, None, None)
        assert c.edges == {}

    def test_user_removal_drops_lower_layer_edge(self) -> None:
        w = world(about("a.x", after=["b.y"]), about("b.y"))
        user = {"a.x": db.Rule(remove_after={"b.y"})}
        c = sorting.compile_rules(w, None, user)
        assert c.edges.get("a.x", {}) == {}
        assert c.removed == [{"after": "a.x", "before": "b.y", "by": "user", "was": ["about:a.x"]}]

    def test_tier_flags(self) -> None:
        w = world(about("fw.core"), about("last.mod"), about(HARMONY))
        rules = {
            "fw.core": db.Rule(load_top=True),
            "last.mod": db.Rule(load_bottom=True),
            HARMONY: db.Rule(load_top=True),  # already tier zero; must not become tier one
        }
        c = sorting.compile_rules(w, rules, None)
        assert c.tier_one == {"fw.core"}
        assert c.tier_three == {"last.mod"}

    def test_incompatibility_is_symmetric(self) -> None:
        w = world(about("a.x", incompat=["b.y"]), about("b.y"))
        c = sorting.compile_rules(w, None, None)
        assert c.incompatible == {"a.x": {"b.y"}, "b.y": {"a.x"}}
        assert sorting.active_incompatibilities(["a.x", "b.y"], c) == [("a.x", "b.y")]
        assert sorting.active_incompatibilities(["a.x"], c) == []


class TestSort:
    def test_tier_pinning(self) -> None:
        """Tier order is absolute: tier0 < tier1 < tier2, whatever the input order."""
        w = world(about(CORE), about("z.mod"), about(HARMONY), about(HUGS))
        c = sorting.compile_rules(w, None, None)
        r = sorting.sort(["z.mod", HUGS, CORE, HARMONY], c, names(w))
        assert r.ok
        assert r.order[:2] == [HARMONY, CORE]  # tier0, alphabetical by name (Harmony < Rimworld)
        assert r.order[2] == HUGS  # tier1
        assert r.order[3] == "z.mod"

    def test_pinned_mod_dependency_joins_the_pin(self) -> None:
        """If Core 'loads after' a plain mod, that mod is pulled into tier 0 ahead of Core."""
        w = world(about(CORE, after=["z.mod"]), about("z.mod"), about("plain.mod"))
        c = sorting.compile_rules(w, None, None)
        r = sorting.sort(["plain.mod", CORE, "z.mod"], c, names(w))
        assert r.ok
        assert set(r.tiers["tier0"]) == {CORE, "z.mod"}
        assert r.order == ["z.mod", CORE, "plain.mod"]

    def test_topological_within_tier_and_alphabetical_ties(self) -> None:
        w = world(about("m.b", after=["m.c"]), about("m.a"), about("m.c"))
        c = sorting.compile_rules(w, None, None)
        r = sorting.sort(["m.b", "m.a", "m.c"], c, names(w))
        assert r.order == ["m.a", "m.c", "m.b"]  # a,c tie at level 0 -> by name; b after c

    def test_tier_expansion_forward_and_reverse(self) -> None:
        w = world(
            about(HUGS, after=["helper.lib"]),
            about("helper.lib"),
            about("last.mod"),
            about("addon.mod", after=["last.mod"]),
            about("plain.mod"),
        )
        c = sorting.compile_rules(w, {"last.mod": db.Rule(load_bottom=True)}, None)
        r = sorting.sort(["plain.mod", "addon.mod", "last.mod", "helper.lib", HUGS], c, names(w))
        assert r.ok
        assert set(r.tiers["tier1"]) == {HUGS, "helper.lib"}  # dependency pulled up
        assert set(r.tiers["tier3"]) == {"last.mod", "addon.mod"}  # dependant pushed down
        assert r.tiers["tier2"] == ["plain.mod"]
        assert r.order.index("helper.lib") < r.order.index(HUGS)
        assert r.order.index("last.mod") < r.order.index("addon.mod")

    def test_mod_in_both_tier1_and_tier3_emitted_once(self) -> None:
        w = world(about("both.mod"), about("x.mod"))
        rules = {"both.mod": db.Rule(load_top=True, load_bottom=True)}
        c = sorting.compile_rules(w, rules, None)
        r = sorting.sort(["x.mod", "both.mod"], c, names(w))
        assert r.ok and r.order.count("both.mod") == 1
        assert r.order[0] == "both.mod"  # earlier tier wins

    def test_deterministic(self) -> None:
        w = world(*(about(f"m.{i}") for i in range(30)))
        c = sorting.compile_rules(w, None, None)
        active = [f"m.{i}" for i in range(29, -1, -1)]
        assert (
            sorting.sort(active, c, names(w)).order
            == sorting.sort(list(reversed(active)), c, names(w)).order
        )

    def test_inactive_cycle_does_not_surface(self) -> None:
        w = world(about("a.x", after=["b.y"]), about("b.y", after=["a.x"]), about("c.z"))
        c = sorting.compile_rules(w, None, None)
        r = sorting.sort(["c.z", "a.x"], c, names(w))  # b.y inactive -> edge dropped
        assert r.ok and r.order == ["a.x", "c.z"]

    def test_cycle_aborts_with_sources(self) -> None:
        w = world(about("a.x", after=["b.y"]), about("b.y"), about("ok.mod"))
        user = {"b.y": db.Rule(load_after={"a.x"})}
        c = sorting.compile_rules(w, None, user)
        r = sorting.sort(["ok.mod", "a.x", "b.y"], c, names(w))
        assert not r.ok
        assert r.order == []  # whole sort abandoned, nothing partial
        assert r.failed_tier == "tier2"
        assert len(r.cycles) == 1
        edges = {(e["after"], e["before"]): e["sources"] for e in r.cycles[0].edges}
        assert edges == {("a.x", "b.y"): ["about:a.x"], ("b.y", "a.x"): ["user"]}

    def test_cycle_in_tier0_still_aborts_everything(self) -> None:
        w = world(about(CORE, after=[HARMONY]), about(HARMONY, after=[CORE]), about("z.mod"))
        c = sorting.compile_rules(w, None, None)
        r = sorting.sort(["z.mod", CORE, HARMONY], c, names(w))
        assert not r.ok and r.failed_tier == "tier0"

    def test_user_removal_breaks_a_cycle(self) -> None:
        w = world(about("a.x", after=["b.y"]), about("b.y", after=["a.x"]))
        c = sorting.compile_rules(w, None, {"b.y": db.Rule(remove_after={"a.x"})})
        r = sorting.sort(["b.y", "a.x"], c, names(w))
        assert r.ok and r.order == ["b.y", "a.x"]
