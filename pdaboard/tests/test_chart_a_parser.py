"""Golden tests for chart_a_parser against the real IN PDA July 2026 examples.

Fixtures live in pdaboard/PDAExamples (NOT committed — internal data). Every test
skips cleanly when fixtures are absent so CI on the public repo stays green.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chart_a_parser import (  # noqa: E402
    parse_chart_a, parse_table_a, sniff_workbook,
    county_from_filename, event_label_from_filename, event_key,
    county_short, norm_status, is_blank_named,
)

PKG = Path(__file__).resolve().parents[1]
EX = PKG / "PDAExamples"
VAL = EX / "Chart As" / "Validated"

needs_fixtures = pytest.mark.skipif(not EX.exists(), reason="PDAExamples fixtures not present")


# ------------------------------------------------------------ pure helpers

@pytest.mark.parametrize("fn,expected", [
    ("Carroll County Chart A - Indiana (June 6 - 11, 2026).xlsx", "Carroll"),
    ("Decatur - Indiana (June 6 - 11, 2026).xlsx", "Decatur"),
    ("Floyd - Indiana (June 16 - 26, 2026).xlsx", "Floyd"),
    ("Morgan County Chart A - Indiana (June 16 - 26, 2026) Completed.xlsx", "Morgan"),
    ("Blank Chart A - Indiana (2026).xlsx", None),
    ("Blank Chart A - Indiana (June 6 - 11, 2026).xlsx", None),
    ("REMC Chart A - Indiana (June 6 - 11, 2026).xlsx", "REMC"),
    ("Carroll White REMC Chart A - Indiana (June 6 - 11, 2026).xlsx", "Carroll White REMC"),
])
def test_county_from_filename(fn, expected):
    assert county_from_filename(fn) == expected


@pytest.mark.parametrize("fn,label", [
    ("X (June 6 - 11, 2026).xlsx", "June 6 - 11, 2026"),
    ("X (June 16 - 26, 2026).xlsx", "June 16 - 26, 2026"),
    ("X (June 6-11, 2026).xlsx", "June 6 - 11, 2026"),          # tight spacing
    ("X (June 26 - July 2, 2026).xlsx", "June 26 - July 2, 2026"),  # cross-month
    ("Blank Chart A - Indiana (2026).xlsx", None),                # year only
])
def test_event_label(fn, label):
    assert event_label_from_filename(fn) == label


def test_event_key_spacing_insensitive():
    assert event_key("June 6 - 11, 2026") == event_key("June 6-11,2026")
    assert event_key("June 6 - 11, 2026") != event_key("June 16 - 26, 2026")
    assert event_key(None) is None


def test_status_and_names():
    assert norm_status("Complete") == "complete"
    assert norm_status("Completed") == "complete"
    assert norm_status("In Progress") == "in_progress"
    assert norm_status(None) == "blank"
    assert county_short("Floyd County") == "Floyd"
    assert county_short("St. Joseph County") == "St. Joseph"
    assert is_blank_named("Blank Chart A - Indiana (2026).xlsx")
    assert not is_blank_named("Benton Chart A - Indiana (June 6 - 11, 2026).xlsx")


# ------------------------------------------------------------ Chart A goldens

@needs_fixtures
def test_floyd_e1_golden():
    ca = parse_chart_a(VAL / "Floyd - Indiana (June 6 - 11, 2026).xlsx")
    assert ca.county == "Floyd County"
    assert ca.county_key == "Floyd"
    assert ca.county_source == "cell"
    assert ca.population == 80484
    assert ca.county_threshold == pytest.approx(391152.24)
    assert ca.inspector == "John Lynn"
    assert ca.event_label == "June 6 - 11, 2026"
    assert len(ca.applicants) == 1
    a = ca.applicants[0]
    assert a.applicant == "Floyd County Road Dept"
    assert a.status_norm == "complete"
    assert a.cats["A"] == pytest.approx(13110.95)
    assert a.cats["C"] == pytest.approx(7591.47)
    assert a.total_calc == pytest.approx(20702.42)
    assert ca.emergency_calc == pytest.approx(13110.95)
    assert ca.permanent_calc == pytest.approx(7591.47)
    assert ca.total_calc == pytest.approx(20702.42)
    assert ca.content_status == "complete"
    assert a.comment.startswith("Category A")
    # workbook agrees with recomputation -> zero mismatch flags
    assert not [f for f in ca.flags if "MISMATCH" in f["code"]]


@needs_fixtures
def test_benton_e1_golden():
    ca = parse_chart_a(VAL / "Benton Chart A - Indiana (June 6 - 11, 2026).xlsx")
    assert ca.county_key == "Benton"
    assert ca.population == 8719
    assert len(ca.applicants) == 3
    assert ca.emergency_calc == pytest.approx(68542.89)
    assert ca.permanent_calc == pytest.approx(7760.29)
    assert ca.total_calc == pytest.approx(76303.18)
    assert ca.content_status == "complete"          # even the $0 applicant is Complete
    # over its $42,374.34 threshold
    assert ca.total_calc > ca.county_threshold


@needs_fixtures
def test_benton_e2_empty_chart_flags():
    """June 16-26 Benton: county dropdown never set, no applicants."""
    ca = parse_chart_a(VAL / "Benton Chart A - Indiana (June 16 - 26, 2026).xlsx")
    assert ca.county_cell_raw is None
    assert ca.county_source == "filename"           # rescued from filename
    assert ca.county_key == "Benton"
    assert ca.is_empty and not ca.is_template
    assert ca.content_status == "empty"
    codes = {f["code"] for f in ca.flags}
    assert "NO_COUNTY_CELL" in codes
    assert "EMPTY_CHART" in codes


@needs_fixtures
def test_morgan_completed_golden():
    ca = parse_chart_a(VAL / "Morgan County Chart A - Indiana (June 16 - 26, 2026) Completed.xlsx")
    assert ca.county_key == "Morgan"
    assert ca.event_label == "June 16 - 26, 2026"
    assert len(ca.applicants) == 2
    assert ca.total_calc == pytest.approx(9363.05)
    assert ca.emergency_calc == pytest.approx(9363.05)
    assert ca.permanent_calc == 0.0
    assert ca.content_status == "complete"


@needs_fixtures
def test_decatur_in_progress():
    ca = parse_chart_a(EX / "Chart As" / "Decatur - Indiana (June 6 - 11, 2026).xlsx")
    assert ca.county_key == "Decatur"
    assert len(ca.applicants) == 1
    assert ca.applicants[0].status_norm == "in_progress"
    assert ca.total_calc == 0.0
    assert ca.content_status == "active"
    assert ca.applicants[0].comment            # validation notes already present
    # rich-text formatting from the workbook survives into comment_html
    html = ca.applicants[0].comment_html
    assert "<b>" in html and "Estimated: $43,715.59" in html
    assert "<script" not in html.lower()       # escaped, pipeline-safe HTML only


@needs_fixtures
def test_every_example_chart_parses_and_reconciles():
    """Sweep: every Chart A in the fixtures parses; recomputed totals match
    the workbook's own cells (or the mismatch is flagged, never silent)."""
    files = [p for p in EX.rglob("*.xlsx")
             if not p.name.startswith("~$") and sniff_workbook(p) == "chart_a"]
    assert len(files) >= 8
    for p in files:
        ca = parse_chart_a(p)
        assert ca.total_calc == pytest.approx(ca.emergency_calc + ca.permanent_calc)
        if ca.wb_total is not None:
            mismatch_flagged = any(f["code"] == "COUNTY_TOTAL_MISMATCH" for f in ca.flags)
            assert (abs(ca.wb_total - ca.total_calc) <= 0.005) or mismatch_flagged, p.name
        for a in ca.applicants:
            assert a.total_calc == pytest.approx(sum(a.cats.values()), abs=0.01)


# ------------------------------------------------------------ Table A goldens

@needs_fixtures
def test_table_a_golden():
    p = EX / "IN PDA - July 2026.xlsx"
    assert sniff_workbook(p) == "table_a"
    ta = parse_table_a(p)
    assert ta.meta["state_code"] == "IN"
    assert ta.meta["state_population"] == 6785528
    assert ta.meta["state_pci"] == pytest.approx(1.94)
    assert ta.meta["county_pci"] == pytest.approx(4.86)
    assert len(ta.counties) == 92                    # all Indiana counties
    assert ta.counties[0]["county"] == "Adams"
    adams = ta.counties[0]
    assert adams["population"] == 35809
    assert adams["county_pci_target"] == pytest.approx(35809 * 4.86)
    # example tracker is not yet filled in
    assert all(c["total_entered"] == 0 for c in ta.counties)
    assert ta.subrecipients == []


@needs_fixtures
def test_sniffer_labels():
    assert sniff_workbook(VAL / "Floyd - Indiana (June 6 - 11, 2026).xlsx") == "chart_a"
    assert sniff_workbook(EX / "IN PDA - July 2026.xlsx") == "table_a"
    assert sniff_workbook(EX / "query.xlsx") == "other"
