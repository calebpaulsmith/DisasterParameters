"""End-to-end pipeline golden test against the PDAExamples drop.

Slow (~2 min: parses every workbook). Asserts the gold model facts that the
board displays — if any of these break, the boss sees wrong numbers.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import build, load_manifest  # noqa: E402

PKG = Path(__file__).resolve().parents[1]
EX = PKG / "PDAExamples"
needs_fixtures = pytest.mark.skipif(not EX.exists(), reason="PDAExamples fixtures not present")


@pytest.fixture(scope="module")
def board(tmp_path_factory):
    out = tmp_path_factory.mktemp("pda_out")
    manifest = load_manifest(Path(__file__).resolve().parents[1] / "manifest.json")
    return build(EX, manifest, out)


@needs_fixtures
def test_scope_and_events(board):
    assert board["summaries"]["E1"]["counties_total"] == 28
    assert {e["event_id"] for e in board["events"]} == {"E1", "E2"}


@needs_fixtures
def test_e1_totals_golden(board):
    s = board["summaries"]["E1"]
    # Benton 76,303.18 + Floyd 20,702.42 + Steuben 10,138.60 (+ Carroll/Decatur/Morgan $0)
    assert s["validated_total"] == pytest.approx(107144.20, abs=0.01)
    assert s["state_threshold"] == pytest.approx(6785528 * 1.94, abs=1)
    assert s["counties_met_100"] == 1          # Benton at 180%
    assert s["counties_ready"] == 4            # Benton, Floyd, Morgan, Steuben


@needs_fixtures
def test_combined_total(board):
    # E2 adds Floyd 25,689.14 + Morgan 9,363.05
    assert board["summaries"]["ALL"]["validated_total"] == pytest.approx(142196.39, abs=0.01)


@needs_fixtures
def test_four_stage_model(board):
    rows = {(r["county"], r["event_id"]): r for r in board["counties"]}
    assert rows[("Benton", "E1")]["stage"] == 3            # Ready for Table A (SP wins over dup)
    assert rows[("Benton", "E1")]["ingested"] is True
    assert rows[("Decatur", "E1")]["stage"] == 1           # Working — county files
    assert rows[("Carroll", "E1")]["stage"] == 1
    assert rows[("Cass", "E1")]["stage"] == 1              # chart in SP, not dropped
    assert rows[("Cass", "E1")]["ingested"] is False
    assert rows[("Franklin", "E1")]["stage"] == 0          # docs but no Chart A
    assert all(r["stage"] != 4 for r in board["counties"])  # nothing entered yet


@needs_fixtures
def test_threshold_math(board):
    rows = {(r["county"], r["event_id"]): r for r in board["counties"]}
    b = rows[("Benton", "E1")]
    assert b["county_threshold"] == pytest.approx(42374.34)
    assert b["pct_of_target"] == pytest.approx(180.1, abs=0.1)
    assert b["money_tier"] == "met_100"


@needs_fixtures
def test_files_and_health(board):
    # per-county file TREE: nodes are folders + docs, `disp` relative to the
    # county folder, and `prefix_path` is what the links are composed from
    tree = board["files"]["Decatur"]
    assert tree["prefix_path"].endswith("/Damage Data/Counties/Decatur")
    assert any(n["disp"].endswith(".pdf") and not n["folder"] for n in tree["nodes"])
    assert any(n["folder"] for n in tree["nodes"])               # subfolders kept
    assert any("/" in n["disp"] for n in tree["nodes"])          # nested docs kept
    codes = {h["code"] for h in board["health"]}
    assert "EMPTY_CHART" in codes              # Benton E2 / Morgan E1 empties are flagged
    # dollars conserve: county rows == summary total (REMC charts are parked)
    tot = sum(r["validated_total"] or 0 for r in board["counties"])
    assert tot == pytest.approx(board["summaries"]["ALL"]["validated_total"], abs=0.01)
    assert "remcs" not in board                # REMC damage arrives via county charts


@needs_fixtures
def test_guide_math(board):
    """Statewide inclusion rule per the PDA Guide (July 2025), 'Per Capita
    Impact Calculations': >=100% counties always count; 50-99% counties count
    only when >=100% counties alone cover 75% of the statewide PCI; <50% never.
    """
    g1 = board["summaries"]["E1"]["guide_math"]
    assert g1["full"] == pytest.approx(76303.18)          # Benton (180% of PCI)
    assert g1["n_full"] == 1
    assert g1["half"] == 0
    assert g1["below"] == pytest.approx(107144.20 - 76303.18, abs=0.01)  # Floyd+Steuben
    assert g1["gate75_ok"] is False        # Benton alone is nowhere near 75% of ~$13.2M
    assert g1["countable"] == pytest.approx(76303.18)

    g2 = board["summaries"]["E2"]["guide_math"]
    assert g2["full"] == 0 and g2["countable"] == 0       # Floyd/Morgan both <50%

    ga = board["summaries"]["ALL"]["guide_math"]
    assert ga["countable"] == pytest.approx(76303.18)
    # conservation: tiers == raw validated total
    assert ga["full"] + ga["half"] + ga["below"] == \
        pytest.approx(board["summaries"]["ALL"]["validated_total"], abs=0.01)


@needs_fixtures
def test_snapshot_written(board, tmp_path_factory):
    assert len(board["snapshots"]) == 1
    assert board["movers"] == []               # first snapshot has no deltas
    assert board["snapshots"][0]["events"]["E1"]["countable"] == pytest.approx(76303.18)
