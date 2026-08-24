"""Golden tests for sp_filetree (query.xlsx parsing, stages, matching)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sp_filetree import (  # noqa: E402
    load_filetree, stage_from_segments, county_folder_of, looks_like_chart_a,
    match_dropped_file, scope_counties, STAGE_LABELS,
)

PKG = Path(__file__).resolve().parents[1]
EX = PKG / "PDAExamples"
needs_fixtures = pytest.mark.skipif(not EX.exists(), reason="PDAExamples fixtures not present")


# ------------------------------------------------------------ stage engine

@pytest.mark.parametrize("segs,rank", [
    (["IN PDA July 2026", "Damage Data", "Chart A's", "2. Ready for Table A", "Entered in Table A"], 4),
    (["IN PDA July 2026", "Damage Data", "Chart A's", "2. Ready for Table A"], 3),
    (["IN PDA July 2026", "Damage Data", "Chart A's", "1. For PDA Lead Review"], 2),
    (["IN PDA July 2026", "Damage Data", "Chart A's"], 2),
    (["Chart As", "Validated"], 3),          # local-drop convention
    (["Chart As"], 2),
    (["IN PDA July 2026", "Damage Data", "Counties", "Benton"], 1),
    (["IN PDA July 2026", "Damage Data", "Counties", "Benton", "Benton County EMA"], 1),
    (["Final Products"], 0),
])
def test_stage_ranks(segs, rank):
    got, _ = stage_from_segments(segs)
    assert got == rank, f"{segs} -> {got}, wanted {rank} ({STAGE_LABELS[rank]})"


def test_county_folder():
    segs = ["x", "Damage Data", "Counties", "Benton", "Benton County EMA"]
    assert county_folder_of(segs) == "Benton"
    assert county_folder_of(["x", "Damage Data", "Counties", "REMCs", "SCI REMC"]) == "REMCs"
    assert county_folder_of(["x", "Damage Data", "Chart A's"]) is None


@pytest.mark.parametrize("name,expected", [
    ("Benton Chart A - Indiana (June 6 - 11, 2026).xlsx", True),
    ("Decatur - Indiana (June 6 - 11, 2026).xlsx", True),
    ("Blank Chart A - Indiana (2026).xlsx", True),
    ("REMC Chart A - Indiana (June 16 - 26, 2026).xlsx", True),
    ("Applicant Cost Tracking Sheet.xlsx", False),
    ("6-15-26 STORM.xlsx", False),
    ("indiana_remc_counties.xlsx", False),
    ("Expense estimates.xlsx", False),
    ("~$Benton Chart A - Indiana (June 6 - 11, 2026).xlsx", False),
    ("Storm Response for Disaster.pdf", False),
])
def test_looks_like_chart_a(name, expected):
    assert looks_like_chart_a(name) is expected


# ------------------------------------------------------------ real query.xlsx

@needs_fixtures
def test_load_filetree_golden():
    rows = load_filetree(EX / "query.xlsx")
    assert len(rows) == 327
    items = [r for r in rows if r.is_item]
    assert all(r.full_path.startswith("teams/") for r in rows)
    # a known row: the validated Floyd chart sits in '2. Ready for Table A'
    floyd = [r for r in items if r.name == "Floyd - Indiana (June 6 - 11, 2026).xlsx"]
    assert len(floyd) == 1
    assert floyd[0].stage == 3
    assert floyd[0].size == 47268
    assert floyd[0].modified_by  # author survives the round trip


@needs_fixtures
def test_scope_counties_golden():
    rows = load_filetree(EX / "query.xlsx")
    scope = scope_counties(rows)
    assert "Benton" in scope and "Floyd" in scope and "REMCs" in scope
    assert "Franklin" in scope          # county with docs but no Chart A yet
    assert len(scope) >= 25


@needs_fixtures
def test_match_benton_duplicate_resolves_to_highest_stage():
    """Benton E1 exists in Counties/Benton AND 2. Ready for Table A (same name,
    same size) -> canonical match must pick the higher stage and flag it."""
    rows = load_filetree(EX / "query.xlsx")
    m = match_dropped_file("Benton Chart A - Indiana (June 6 - 11, 2026).xlsx", 49817, rows)
    assert m["method"] == "ambiguous_highest_stage"
    assert m["row"].stage == 3
    assert "AMBIGUOUS_MATCH" in m["flags"]


@needs_fixtures
def test_match_decatur_resaved_name_unique():
    """Local Decatur file was re-saved (size differs from export) but the name
    is unique -> match by name, note the size drift, stage = Working."""
    rows = load_filetree(EX / "query.xlsx")
    m = match_dropped_file("Decatur - Indiana (June 6 - 11, 2026).xlsx", 50182, rows)
    assert m["method"] == "name_unique"
    assert "SIZE_MISMATCH" in m["flags"]
    assert m["row"].stage == 1
    assert m["row"].county_folder == "Decatur"


@needs_fixtures
def test_match_unmatched():
    rows = load_filetree(EX / "query.xlsx")
    m = match_dropped_file("Nowhere Chart A - Indiana (June 6 - 11, 2026).xlsx", None, rows)
    assert m["method"] == "unmatched"
    assert m["row"] is None
