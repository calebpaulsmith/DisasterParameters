"""SharePoint link resolution: query.iqy parsing + the manifest -> query.xlsx
-> .iqy precedence in pipeline.resolve_links(). Pure functions — no workbooks,
so these run fast and never need PDAExamples."""
from pathlib import Path

import pytest

import sp_filetree as sp
import pipeline as pl

HERE = Path(__file__).resolve().parent.parent

IQY = """WEB
1
https://usfema.sharepoint.com/teams/R5/org/x/_vti_bin/owssvr.dll?XMLDATA=1&List=abc&View=def&RowLimit=0&RootFolder=%2fteams%2fR5%2forg%2fx%2fPA%20Yellow%20Pages%2fOngoing%20PDA%27s%2fIL%20PDA%20July%202026

Selection=abc-def
Formatting=None
SharePointApplication=https://usfema.sharepoint.com/teams/R5/org/x/_vti_bin
SharePointListView=def
SharePointListName=abc
RootFolder=/teams/R5/org/x/PA%20Yellow%20Pages/Ongoing%20PDA%27s/IL%20PDA%20July%202026
"""


def test_parse_iqy_host_and_root():
    q = sp.parse_iqy(IQY)
    assert q["host"] == "https://usfema.sharepoint.com"
    assert q["root_path"] == "/teams/R5/org/x/PA Yellow Pages/Ongoing PDA's/IL PDA July 2026"
    assert q["root_name"] == "IL PDA July 2026"
    # re-encoded for the browser, separators intact
    assert q["root_url"].endswith("/PA%20Yellow%20Pages/Ongoing%20PDA%27s/IL%20PDA%20July%202026")
    assert q["master_folder"] == q["root_url"] + "/Damage%20Data/Counties"
    assert q["master_folder_assumed"] is True     # no export to confirm it
    assert q["list_id"] == "abc" and q["view_id"] == "def"


def test_parse_iqy_falls_back_to_the_url_line():
    """Older exports carry RootFolder only in the query string."""
    trimmed = "\n".join(l for l in IQY.splitlines()
                        if not l.lower().startswith("rootfolder="))
    q = sp.parse_iqy(trimmed)
    assert q["root_name"] == "IL PDA July 2026"


def test_parse_iqy_invents_nothing():
    q = sp.parse_iqy("not an iqy at all")
    assert q["host"] is None and q["root_path"] is None
    assert q["sharepoint_base"] is None and q["master_folder"] is None


def test_resolve_links_prefers_the_manifest(tmp_path):
    (tmp_path / "query.iqy").write_text(IQY, encoding="utf-8")
    links = pl.resolve_links(tmp_path, {"sharepoint_base": "https://other/",
                                        "master_folder": "https://other/Counties/"}, [])
    assert links["sharepoint_base"] == "https://other"      # trailing slash trimmed
    assert links["master_folder"] == "https://other/Counties"
    assert links["source"] == "manifest"


def test_resolve_links_from_the_drops_iqy(tmp_path):
    (tmp_path / "query IL 2026.iqy").write_text(IQY, encoding="utf-8")
    links = pl.resolve_links(tmp_path, {}, [])
    assert links["sharepoint_base"] == "https://usfema.sharepoint.com"
    assert links["root_name"] == "IL PDA July 2026"
    assert links["master_folder"].endswith("/IL%20PDA%20July%202026/Damage%20Data/Counties")
    assert links["master_folder_assumed"] is True
    assert links["source"] == "query IL 2026.iqy"


def test_resolve_links_no_source_stays_empty(tmp_path):
    links = pl.resolve_links(tmp_path, {}, [])
    assert links["sharepoint_base"] == "" and links["master_folder"] == ""
    assert links["sp_root_url"] is None


MASTER_IQY = IQY.replace(
    "/PA%20Yellow%20Pages/Ongoing%20PDA%27s/IL%20PDA%20July%202026",
    "/PA%20Yellow%20Pages/Ongoing%20PDA%27s").replace(
    "%2fPA%20Yellow%20Pages%2fOngoing%20PDA%27s%2fIL%20PDA%20July%202026",
    "%2fPA%20Yellow%20Pages%2fOngoing%20PDA%27s")

MANIFESTS = {
    "IL": {"pda_id": "IL_PDA_July_2026", "title": "IL PA PDA - July 2026", "state": "IL"},
    "MI": {"pda_id": "MI_PDA_May_2026", "title": "MI PA PDA - May 2026", "state": "MI"},
}


def _row(path, name, item=True):
    r = sp.FileRow(name=name, path=path, item_type="Item" if item else "Folder",
                   modified=None, modified_by="", size=None)
    r.stage, r.stage_basis = sp.stage_from_segments(r.segments)
    r.county_folder = sp.county_folder_of(r.segments)
    return r


def _master_export():
    """A library-wide export: three PDAs side by side under one root."""
    root = "teams/R5/org/x/PA Yellow Pages/Ongoing PDA's"
    rows = []
    for pda, counties in (("IL PDA July 2026", ["Cook", "Will"]),
                          ("MI PDA May 2026", ["Alpena"]),
                          ("IN PDA July 2026", ["Benton"])):
        base = f"{root}/{pda}/Damage Data"
        for c in counties:
            rows.append(_row(f"{base}/Counties", c, item=False))
            rows.append(_row(f"{base}/Counties/{c}", f"{c} Chart A - x (2026).xlsx"))
        rows.append(_row(f"{base}/Chart A's/2. Ready for Table A",
                         f"{counties[0]} Chart A - x (2026).xlsx"))
    return rows


def test_master_export_lists_every_pda():
    names = [c.rsplit("/", 1)[-1] for c in sp.pda_root_candidates(_master_export())]
    assert names == ["IL PDA July 2026", "IN PDA July 2026", "MI PDA May 2026"]


@pytest.mark.parametrize("st,counties", [("IL", ["Cook", "Will"]), ("MI", ["Alpena"])])
def test_master_export_narrows_to_this_pda(st, counties, tmp_path):
    rows = _master_export()
    root, cands = pl.choose_pda_root(rows, MANIFESTS[st])
    assert root.endswith(f"/{st} PDA " + ("July 2026" if st == "IL" else "May 2026"))
    assert len(cands) == 3
    kept = sp.filter_rows_under(rows, root)
    assert sp.scope_counties(kept) == counties          # no other PDA's counties
    (tmp_path / "master.iqy").write_text(MASTER_IQY, encoding="utf-8")
    links = pl.resolve_links(tmp_path, MANIFESTS[st], kept, pda_root=root)
    assert links["master_folder_assumed"] is False      # counties path seen in the export
    assert f"/{st}%20PDA%20" in links["master_folder"]
    assert links["master_folder"].endswith("/Damage%20Data/Counties")


def test_master_export_refuses_to_guess_an_unknown_pda():
    root, cands = pl.choose_pda_root(
        _master_export(), {"pda_id": "OH_PDA_Jan_2027", "title": "OH PA PDA - Jan 2027",
                           "state": "OH"})
    assert root is None and len(cands) == 3     # caller flags AMBIGUOUS_PDA_EXPORT


def test_sp_folder_pins_the_pda_in_a_master_export():
    rows = _master_export()
    root, _ = pl.choose_pda_root(rows, MANIFESTS["IL"], sp_folder="IN PDA July 2026")
    assert root.endswith("/IN PDA July 2026")           # explicit beats the name match


def test_master_iqy_alone_cannot_name_the_pda(tmp_path):
    """A library-wide .iqy has no listing — so the PDA folder is unknowable
    until sp_folder (or the board's picker) supplies it. Never guessed."""
    (tmp_path / "query.iqy").write_text(MASTER_IQY, encoding="utf-8")
    a = pl.resolve_links(tmp_path, MANIFESTS["IL"], [])
    assert a["root_path"] is None and a["master_folder"] == ""
    assert a["master_root_path"].endswith("/Ongoing PDA's")

    b = pl.resolve_links(tmp_path, dict(MANIFESTS["IL"], sp_folder="IL PDA July 2026"), [])
    assert b["root_path"].endswith("/Ongoing PDA's/IL PDA July 2026")
    assert b["pda_folder"] == "IL PDA July 2026"
    assert b["master_folder_assumed"] is True           # convention, nothing to confirm it


def test_single_pda_iqy_is_not_treated_as_a_parent(tmp_path):
    (tmp_path / "query.iqy").write_text(IQY, encoding="utf-8")
    links = pl.resolve_links(tmp_path, MANIFESTS["IL"], [])
    assert links["master_root_path"] is None
    assert links["root_path"].endswith("/IL PDA July 2026")


@pytest.mark.skipif(not (HERE / "PDAExamples" / "query.xlsx").exists(),
                    reason="IN export absent")
def test_export_pins_the_folders_iqy_pins_the_host(tmp_path):
    """The export carries server-relative paths (folders, verified) and the
    .iqy carries the host — resolve_links takes each from its own source."""
    rows = sp.load_filetree(HERE / "PDAExamples" / "query.xlsx")
    (tmp_path / "query.iqy").write_text(IQY, encoding="utf-8")     # an IL .iqy...
    links = pl.resolve_links(tmp_path, {}, rows)
    assert links["sharepoint_base"] == "https://usfema.sharepoint.com"
    assert links["root_name"] == "IN PDA July 2026"                # ...IN folders win
    assert links["counties_path"].endswith("/IN PDA July 2026/Damage Data/Counties")
    assert links["master_folder"].endswith("/IN%20PDA%20July%202026/Damage%20Data/Counties")
    assert links["master_folder_assumed"] is False                 # seen in the export
