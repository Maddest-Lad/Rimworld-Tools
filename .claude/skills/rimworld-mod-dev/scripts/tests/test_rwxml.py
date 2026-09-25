"""Tests for the mod-dev helpers: load folders, def document, patch emulation, inheritance."""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import decompile
import patchops
import rwxml
from rwxml import Inheritance, Mod, build_document, load_folders, xml_files

V16 = (1, 6)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text).strip() + "\n", encoding="utf-8")
    return path


def make_mod(tmp: Path, name: str, pid: str | None = None, **files: str) -> Mod:
    root = tmp / name
    write(
        root / "About" / "About.xml",
        f"<ModMetaData><name>{name}</name><packageId>{pid or 'test.' + name.lower()}"
        "</packageId></ModMetaData>",
    )
    for rel, text in files.items():
        write(root / rel.replace("__", "/"), text)
    return rwxml.read_about(root)


# --- load folders ---------------------------------------------------------------------------


def test_default_load_folders_prefer_exact_version(tmp_path):
    mod = make_mod(tmp_path, "A")
    for d in ("1.5", "1.6", "Common"):
        (mod.root / d).mkdir()
    assert load_folders(mod, version=V16) == [mod.root / "1.6", mod.root / "Common", mod.root]


def test_default_load_folders_fall_back_to_newest_older_version(tmp_path):
    mod = make_mod(tmp_path, "A")
    for d in ("1.4", "1.5", "1.7"):
        (mod.root / d).mkdir()
    assert load_folders(mod, version=V16)[0] == mod.root / "1.5"


def test_loadfolders_xml_conditions_and_priority(tmp_path):
    mod = make_mod(
        tmp_path,
        "A",
        **{"LoadFolders.xml": """
        <loadFolders>
          <v1.5><li>/</li><li>1.5</li></v1.5>
          <v1.6>
            <li>/</li>
            <li>1.6</li>
            <li IfModActive="Ludeon.RimWorld.Biotech">Mods/Biotech</li>
            <li IfModNotActive="other.mod_steam">Mods/NoOther</li>
          </v1.6>
        </loadFolders>"""},
    )
    got = load_folders(mod, active={"ludeon.rimworld.biotech", "other.mod"}, version=V16)
    # later entries win (descending priority), IfModNotActive ignores the _steam suffix
    assert got == [mod.root / "Mods/Biotech", mod.root / "1.6", mod.root]
    assert load_folders(mod, active=set(), version=V16) == [
        mod.root / "Mods/NoOther",
        mod.root / "1.6",
        mod.root,
    ]


def test_xml_files_first_relative_path_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(rwxml, "game_version", lambda game=None: (1, 6, 0))
    mod = make_mod(
        tmp_path,
        "A",
        **{
            "Defs__Things.xml": "<Defs><ThingDef><defName>Root</defName></ThingDef></Defs>",
            "1.6__Defs__Things.xml": "<Defs><ThingDef><defName>V16</defName></ThingDef></Defs>",
            "Common__Defs__Other.xml": "<Defs><ThingDef><defName>Common</defName></ThingDef></Defs>",
        },
    )
    files = xml_files(mod, "Defs")
    assert [f.relative_to(mod.root).as_posix() for f in files] == [
        "1.6/Defs/Things.xml",
        "Common/Defs/Other.xml",
    ]


# --- patch operations -----------------------------------------------------------------------

BASE = """
<Defs>
  <ThingDef Name="BaseThing" Abstract="True">
    <statBases><Mass>1</Mass></statBases>
    <tags><li>a</li></tags>
  </ThingDef>
  <ThingDef ParentName="BaseThing">
    <defName>Rock</defName>
    <label>rock</label>
    <tags><li>b</li></tags>
  </ThingDef>
  <ThingDef ParentName="BaseThing">
    <defName>Stick</defName>
    <label>stick</label>
    <tags Inherit="False"><li>c</li></tags>
    <statBases><Mass>2</Mass></statBases>
  </ThingDef>
</Defs>"""


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(rwxml, "game_version", lambda game=None: (1, 6, 0))
    base = make_mod(tmp_path, "Core", "Ludeon.RimWorld", **{"Defs__Base.xml": BASE})
    return tmp_path, base


def run(tmp_path, base, patch: str, active_extra=()):
    mod = make_mod(tmp_path, "P", **{"Patches__P.xml": f"<Patch>{patch}</Patch>"})
    mods = [base, *active_extra, mod]
    doc = build_document(mods)
    errors, warnings = [], []
    results = patchops.run_all(doc, mods, errors, warnings, report_for={mod.key})
    return doc, [r for _, r in results], errors, warnings


def texts(doc, xpath):
    return [n if isinstance(n, str) else (n.text or "").strip() for n in doc.select(xpath)]


def test_add_replace_remove_and_counts(world):
    tmp, base = world
    doc, res, errors, _ = run(
        tmp,
        base,
        """
      <Operation Class="PatchOperationAdd">
        <xpath>Defs/ThingDef[defName="Rock" or defName="Stick"]/tags</xpath>
        <value><li>new</li></value>
      </Operation>
      <Operation Class="PatchOperationReplace">
        <xpath>/Defs/ThingDef[defName="Rock"]/label/text()</xpath>
        <value>boulder</value>
      </Operation>
      <Operation Class="PatchOperationRemove">
        <xpath>Defs/ThingDef[defName="Stick"]/statBases</xpath>
      </Operation>
      <Operation Class="PatchOperationAdd">
        <xpath>Defs/ThingDef[defName="Missing"]</xpath>
        <value><x/></value>
      </Operation>""",
    )
    assert [r.matched for r in res] == [2, 1, 1, 0]
    assert [r.ok for r in res] == [True, True, True, False]
    assert texts(doc, 'Defs/ThingDef[defName="Rock"]/tags/li') == ["b", "new"]
    assert texts(doc, 'Defs/ThingDef[defName="Rock"]/label') == ["boulder"]
    assert doc.select('Defs/ThingDef[defName="Stick"]/statBases') == []
    assert errors == []


def test_insert_order_setname_and_attributes(world):
    tmp, base = world
    doc, res, _, _ = run(
        tmp,
        base,
        """
      <Operation Class="PatchOperationInsert">
        <xpath>Defs/ThingDef[defName="Rock"]/label</xpath>
        <order>Append</order>
        <value><a/><b/></value>
      </Operation>
      <Operation Class="PatchOperationSetName">
        <xpath>Defs/ThingDef[defName="Rock"]/a</xpath>
        <name>renamed</name>
      </Operation>
      <Operation Class="PatchOperationAttributeAdd">
        <xpath>Defs/ThingDef[@Name="BaseThing"]</xpath>
        <attribute>Abstract</attribute>
        <value>False</value>
      </Operation>
      <Operation Class="PatchOperationAttributeSet">
        <xpath>Defs/ThingDef[defName="Rock"]</xpath>
        <attribute>MayRequire</attribute>
        <value>x.y</value>
      </Operation>""",
    )
    rock = doc.select('Defs/ThingDef[defName="Rock"]')[0]
    assert [c.tag for c in rock if isinstance(c.tag, str)][:4] == [
        "defName",
        "label",
        "renamed",
        "b",
    ]
    assert [r.ok for r in res] == [True, True, False, True]  # Abstract already present
    assert rock.get("MayRequire") == "x.y"


def test_conditional_sequence_mayrequire_and_success(world):
    tmp, base = world
    doc, res, _, warnings = run(
        tmp,
        base,
        """
      <Operation Class="PatchOperationConditional">
        <xpath>Defs/ThingDef[defName="Rock"]/comps</xpath>
        <nomatch Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Rock"]</xpath>
          <value><comps/></value>
        </nomatch>
      </Operation>
      <Operation Class="PatchOperationSequence">
        <operations>
          <li Class="PatchOperationAdd" MayRequire="not.loaded">
            <xpath>Defs/Nothing</xpath><value><x/></value>
          </li>
          <li Class="PatchOperationAdd">
            <xpath>Defs/ThingDef[defName="Rock"]/comps</xpath><value><li>c1</li></value>
          </li>
          <li Class="PatchOperationRemove"><xpath>Defs/Nope</xpath></li>
          <li Class="PatchOperationAdd">
            <xpath>Defs/ThingDef[defName="Rock"]/comps</xpath><value><li>never</li></value>
          </li>
        </operations>
      </Operation>
      <Operation Class="PatchOperationRemove">
        <xpath>Defs/Nope</xpath>
        <success>Always</success>
      </Operation>
      <Operation Class="PatchOperationAdd" MayRequire="not.loaded">
        <xpath>Defs/ThingDef[defName="Rock"]</xpath><value><ran/></value>
      </Operation>""",
    )
    assert [r.ok for r in res] == [True, False, True, True]
    seq = res[1]
    assert "skipped" in seq.children[0].note
    assert [c.ok for c in seq.children[1:]] == [True, False]  # stops at the failing Remove
    assert texts(doc, 'Defs/ThingDef[defName="Rock"]/comps/li') == ["c1"]
    # a MayRequire on a top-level Operation is ignored by the game: it still runs
    assert doc.select('Defs/ThingDef[defName="Rock"]/ran')
    assert any("top-level <Operation>" in w for w in warnings)


def test_findmod_matches_names_not_package_ids(world):
    tmp, base = world
    other = make_mod(tmp, "Other Mod", "some.othermod")
    _, res, _, warnings = run(
        tmp,
        base,
        """
      <Operation Class="PatchOperationFindMod">
        <mods><li>Other Mod</li></mods>
        <match Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Rock"]</xpath><value><x/></value>
        </match>
      </Operation>
      <Operation Class="PatchOperationFindMod">
        <mods><li>some.othermod</li></mods>
        <match Class="PatchOperationAdd">
          <xpath>Defs/ThingDef[defName="Rock"]</xpath><value><y/></value>
        </match>
      </Operation>""",
        active_extra=[other],
    )
    assert res[0].children and res[0].children[0].matched == 1
    assert not res[1].children  # packageId never matches a name
    assert any("compares mod names" in w for w in warnings)


def test_custom_operation_class_is_reported_not_evaluated(world):
    tmp, base = world
    _, res, _, _ = run(
        tmp,
        base,
        """
      <Operation Class="XmlExtensions.PatchOperationSafeAdd">
        <xpath>Defs/ThingDef</xpath>
      </Operation>""",
    )
    assert res[0].unsupported and res[0].ok


def test_bad_patch_root_and_element(world):
    tmp, _base = world
    mod = make_mod(
        tmp,
        "Q",
        **{
            "Patches__A.xml": "<Defs><Operation/></Defs>",
            "Patches__B.xml": "<Patch><Op Class='x'/></Patch>",
        },
    )
    errors: list[str] = []
    patchops.load_operations(mod, set(), errors, [])
    assert any("expected 'Patch'" in e for e in errors)
    assert any("expected 'Operation'" in e for e in errors)


def test_indexed_fast_path_matches_plain_xpath(world):
    tmp, base = world
    doc = build_document([base])
    for xp in (
        'Defs/ThingDef[defName="Rock"]/label',
        '/Defs/ThingDef[defName = "Rock" or defName="Stick"]',
        'Defs/*[defName="Stick"]//li',
        'Defs/ThingDef[defName="X"]',
    ):
        fast = doc.select(xp)
        slow = doc.wrapper.xpath(rwxml.to_document_xpath(xp))
        assert fast == slow, xp
    # adding a new def must invalidate the index
    mod = make_mod(
        tmp,
        "P",
        **{"Patches__P.xml": """<Patch>
      <Operation Class="PatchOperationAdd"><xpath>Defs</xpath>
        <value><ThingDef><defName>New</defName></ThingDef></value></Operation>
      <Operation Class="PatchOperationAdd"><xpath>Defs/ThingDef[defName="New"]</xpath>
        <value><label>n</label></value></Operation></Patch>"""},
    )
    doc = build_document([base, mod])
    doc.select('Defs/ThingDef[defName="Rock"]')  # warm the index
    res = patchops.run_all(doc, [base, mod], [], [], report_for={mod.key})
    assert [r.ok for _, r in res] == [True, True]


# --- inheritance ----------------------------------------------------------------------------


def test_inheritance_merge_rules(world):
    _tmp, base = world
    doc = build_document([base])
    inh = Inheritance(doc)
    rock, stick = doc.select("Defs/ThingDef[defName]")
    r = inh.resolve(rock)
    assert [li.text for li in r.find("tags")] == ["a", "b"]  # lists append
    assert r.findtext("statBases/Mass") == "1"
    s = inh.resolve(stick)
    assert [li.text for li in s.find("tags")] == ["c"]  # Inherit="False"
    assert s.findtext("statBases/Mass") == "2"  # scalar override


def test_parent_lookup_is_scoped_by_load_order(world):
    tmp, base = world
    later = make_mod(
        tmp,
        "Later",
        **{"Defs__D.xml": """<Defs>
      <ThingDef Name="BaseThing" Abstract="True"><label>shadow</label></ThingDef>
      <ThingDef ParentName="BaseThing"><defName>Mine</defName></ThingDef></Defs>"""},
    )
    doc = build_document([base, later])
    inh = Inheritance(doc)
    mine = doc.select('Defs/ThingDef[defName="Mine"]')[0]
    rock = doc.select('Defs/ThingDef[defName="Rock"]')[0]
    assert inh.resolve(mine).findtext("label") == "shadow"  # own mod's parent wins
    assert inh.parent_of(rock).findtext("label") is None  # Core never sees the later mod's


# --- decompile helpers ----------------------------------------------------------------------


def test_find_type_and_outline(tmp_path):
    src = write(
        tmp_path / "Verse" / "Outer.cs",
        """
        namespace Verse;

        public class Outer
        {
        \tpublic int count;

        \tpublic virtual void Tick()
        \t{
        \t}

        \tprivate class Inner
        \t{
        \t}
        }""",
    )
    assert decompile.find_type(tmp_path, "Verse.Outer") == [(src, 3)]
    assert decompile.find_type(tmp_path, "Inner")[0][0] == src
    lines = decompile.outline(src, 3)
    assert any("public virtual void Tick()" in ln for ln in lines)
    assert any("public int count;" in ln for ln in lines)


def test_etree_available():
    assert etree.LXML_VERSION >= (4,)
