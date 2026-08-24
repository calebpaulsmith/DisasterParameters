"""Golden tests: legacy-format (MI/WI May 2026) workbooks + the
pa_pdas_charta builder. Skip when the _17-19 import examples are absent."""
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore", module="openpyxl")

HERE = Path(__file__).resolve().parent.parent
IMP = HERE / "PDAExamples" / "_17-19 import"
MI_TA = (IMP / "MI May 2026" / "MI 2026 Table A"
         / "Table A - Michigan PDA - May 2026.xlsx")
# resolved by glob — the drop has been rearranged before (the pipeline finds
# workbooks at any depth; the test shouldn't pin a folder)
WI_TA = next(iter((IMP / "WI May 2026").rglob("WI PDA - May 2026 - Table A.xlsx")),
             IMP / "WI May 2026" / "WI PDA - May 2026 - Table A.xlsx")
WI_CHART = (IMP / "WI May 2026" / "WI 2026 Chart A"
            / "Chart A's for PDA Lead Review"
            / "Ready for Table A" / "Entered in Table A"
            / "Bayfield County Chart A - Wisconsin (2026).xlsx")

pytestmark = pytest.mark.skipif(not IMP.is_dir(), reason="import examples absent")

from chart_a_parser import parse_chart_a, parse_table_a, sniff_workbook  # noqa: E402
from pa_pdas_charta import build_charta_rows, norm_appl_name, read_pa_pdas_csv  # noqa: E402


def test_sniff_legacy_table_a():
    assert sniff_workbook(MI_TA) == "table_a"
    assert sniff_workbook(WI_TA) == "table_a"
    assert sniff_workbook(WI_CHART) == "chart_a"


def test_legacy_table_a_meta_golden():
    ta = parse_table_a(MI_TA)
    m = ta.meta
    assert m["format"] == "legacy"
    assert m["state_code"] == "MI"
    assert m["state_population"] == 10077331          # PCI Indicator sheet
    assert m["state_pci"] == 1.94 and m["county_pci"] == 4.86
    assert m["pda_start"] == "2026-05-19"
    assert m["incident_start"] == "2026-04-10" and m["incident_end"] == "2026-04-21"
    assert len(ta.subrecipients) == 119
    assert len(ta.counties) == 37                     # SummaryPage county rows
    assert round(sum(s["total_calc"] for s in ta.subrecipients), 2) == 24592236.60


def test_v2_table_a_meta_unpolluted():
    # the IN v2 workbook also HAS a 'PCI Indicator' sheet with stale template
    # leftovers — the legacy fallback must NOT read it for v2
    ta = parse_table_a(HERE / "PDAExamples" / "IN PDA - July 2026.xlsx")
    assert ta.meta["format"] == "v2"
    assert ta.meta["state_code"] == "IN"
    assert ta.meta["state_population"] == 6785528
    assert ta.meta["event_type"] is None              # not the '0' filler
    assert ta.meta["incident_start"] is None          # not the stale PCI date


def test_legacy_chart_a_deduction_comments():
    ca = parse_chart_a(WI_CHART)
    assert ca.county == "Bayfield County" and ca.county_source == "cell"
    assert ca.event_label is None                     # no period in filename
    with_comments = [a for a in ca.applicants if a.comment]
    assert with_comments, "Deduction Comments sheet not joined"


def test_charta_build_golden_mi():
    ta = parse_table_a(MI_TA)
    pa = read_pa_pdas_csv(IMP / "pa_pdas.csv")
    rows, audit = build_charta_rows(ta, [], year=2026, month="May", state="MI",
                                    declaration_number="4925", pa_pdas_rows=pa)
    assert audit["conserved"]
    assert audit["n_rows"] == 119
    assert audit["n_counties"] == 37 and audit["n_met"] == 26
    assert audit["n_linked"] == 67                     # best-effort pa_pdas link
    assert rows[0]["Charta_Id"] == "2026-May-MI-0001"
    assert rows[0]["Pda_Id"] == "2026-May-MI"
    assert rows[0]["State_Threshold"] == 19550022.14   # matches pa_pdas exactly
    alcona = [r for r in rows if r["County"] == "Alcona"]
    assert alcona[0]["County_Pop"] == 10167
    assert alcona[0]["County_Threshold"] == 49411.62   # matches pa_pdas exactly
    assert alcona[0]["Met_Threshold"] is True
    # null convention: blank categories are None, never 0
    assert all(r["Cat_A"] is None or r["Cat_A"] != 0 for r in rows)


def test_norm_appl_name_inversions():
    assert norm_appl_name("East Jordan, City of ") == norm_appl_name("City of East Jordan")
    assert norm_appl_name("Garfield Township") != norm_appl_name("Garfield Charter Township")
    assert norm_appl_name("IRON COUNTY ROAD COMMISSION") == \
        norm_appl_name("Iron County Road Commission")
