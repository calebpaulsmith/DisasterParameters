"""Golden test: COMPLETE-mode pipeline build over the WI May 2026 import
(14 Chart A's + legacy Table A, no query.xlsx). Skips when absent."""
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
DROP = HERE / "PDAExamples" / "_17-19 import" / "WI May 2026"

pytestmark = pytest.mark.skipif(not DROP.is_dir(), reason="WI import absent")


def test_wi_complete_build(tmp_path):
    # met_only=False = full-fidelity path (every county, matches the workbook)
    import pipeline as pl
    manifest = {"pda_id": "WI_TEST", "title": "WI test", "state": "WI",
                "complete": True, "met_only": False,
                "master_folder": "https://x/Counties", "events": []}
    board = pl.build(DROP, manifest, tmp_path)

    assert board["complete"] is True and board["met_only"] is False
    assert board["master_folder"] == "https://x/Counties"
    # single synthesized event (legacy filenames carry no incident period)
    assert [e["event_id"] for e in board["events"]] == ["E1"]
    assert board["events"][0]["key"] is None

    s = board["summaries"]["ALL"]
    assert s["counties_total"] == 14                    # scope from workbooks
    by_stage = s["counties_by_stage"]                   # int keys in-process
    assert by_stage.get(4, by_stage.get("4")) == 14     # everything final
    assert s["validated_total"] == 18251557.18          # == Table A total
    # countable matches the workbook's own SummaryPage "Validated Total"
    assert abs(s["guide_math"]["countable"] - 17661571.69) < 0.01
    assert s["state_threshold"] == 11433812.92          # == pa_pdas to the cent
    assert s["counties_met_100"] == 9

    rows = {r["county"]: r for r in board["counties"]}
    assert len(rows) == 14 and all(r["fips"] for r in rows.values())
    assert rows["Rock"]["applicants_n"] == 21
    assert rows["Bayfield"]["stage"] == 4

    codes = {h["code"] for h in board["health"]}
    assert "SCOPE_FROM_WORKBOOKS" in codes and "NO_EVENT_LABELS" in codes

    html = (tmp_path / "board.html").read_text(encoding="utf-8")
    assert '"complete": true' in html or '"complete":true' in html


def test_wi_met_only_build(tmp_path):
    # met_only (the COMPLETE-mode default): under-threshold counties excluded
    # from the board, disclosed in health + met_only_excluded
    import pipeline as pl
    manifest = {"pda_id": "WI_TEST2", "title": "WI test", "state": "WI",
                "complete": True, "events": []}
    board = pl.build(DROP, manifest, tmp_path)

    assert board["met_only"] is True                     # default under complete
    s = board["summaries"]["ALL"]
    assert s["counties_total"] == 9                      # 5 excluded (2 half, 3 under)
    assert board["met_only_excluded"]["n"] == 5
    # excluded $ = the 50-99 + <50 dollars from the full build
    assert board["met_only_excluded"]["total"] == 1518809.93
    assert s["validated_total"] == s["guide_math"]["countable"] == 16732747.25
    assert {h["code"] for h in board["health"]} >= {"MET_ONLY_EXCLUDED"}
    assert all(r["pct_of_target"] >= 100 for r in board["counties"])
