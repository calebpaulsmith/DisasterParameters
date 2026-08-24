# PA PDAs ChartA Builder (Excel)

The no-Databricks path from a PDA's **Table A** workbook to the
**pa_pdas_charta** structured table. Same math, same columns, same rules as
`../pa_pdas_charta.py` and the `gold_pa_pdas_charta` Databricks table.

## Use

1. Open `PA PDAs ChartA Builder.xlsm` (enable macros), click **Build
   pa_pdas_charta** on the Builder sheet.
2. Browse to the folder holding the PDA's Table A. Chart A workbooks
   anywhere under that folder are **optional** — say Yes to also pull
   per-applicant comments, applicant types, and inspectors (dollars always
   come from the Table A either way).
3. Verify the prompts: Year / Month / State / Declaration number (defaults
   read from the Table A — these are the pa_pdas natural-key values).
4. The `pa_pdas_charta` sheet now holds an Excel Table.
   **Power BI: Get Data > Excel workbook > pa_pdas_charta.**

Both Table A generations are handled (RVAR-era v2 like IN 2026, and the
SummaryPage-era legacy like MI/WI May 2026) — fields are found by label,
not fixed cells.

## Linking to the existing pa_pdas table

`pa_pdas` is never modified. Every output row carries
`Pda_Id = Year-Month-State`; add the same calculated column on the pa_pdas
side in Power BI (`[Year] & "-" & [Month] & "-" & [State]`) and relate the
tables. Optionally paste a pa_pdas extract (header row included) onto a
sheet named `pa_pdas` before building to get the best-effort per-row link
(`In_Pa_Pdas` / `Pa_Pdas_Applicant_Name`). No link is normal — pa_pdas
names are hand-curated and multi-county applicants sit under
County="Multiple", and a charta build usually happens before the pa_pdas
row exists.

## Sheets

- `Builder` — instructions + the button.
- `pa_pdas_charta` — the output table (rebuilt each run).
- `openfema` — reserved for OpenFEMA reference data (prior PA history),
  imported separately; the macro never writes it.
- `pa_pdas` (optional, you create it) — extract of the existing table for
  the row link.

## Maintaining the code

`modChartA.bas` in this folder is the source of truth. After editing it:
in the VBE remove module `modChartA`, then File > Import File >
`modChartA.bas`. Keep the file pure ASCII (VBA imports ANSI — smart
dashes/quotes garble) and never name a local variable the same as a
module-level constant (VBA is case-insensitive; shadowing broke the build
once already). `BuildChartaAuto(folder, yr, mo, st, dn, useCharts)` is the
headless entry point for testing. The macro runs with manual calculation —
the source workbooks recalc slowly.

Dollar conservation is asserted every run (rows vs the Table A input
sheet); a failure means the output is not trustworthy and nothing should
be imported.
