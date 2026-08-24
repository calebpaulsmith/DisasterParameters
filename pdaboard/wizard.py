"""PDA Board build wizard -- point it at ONE folder, get one board.

    python wizard.py [path-to-your-PDA-folder]

Download the PDA's folder from SharePoint -- the whole thing (e.g. the PDA
folder or "Final Products"), or just a folder you piled the Chart A's into --
and point the wizard at it. It reads what is inside where it sits; nothing
is rearranged, staged, or copied:

  "...Table A..." .xlsx   -> the Table A master (indicators + county figures)
  "...Chart A..." .xlsx   -> Chart A's. Stage = the folder each one sits in
                             ("Entered in Table A" / "2. Ready for Table A" /
                             "1. For PDA Lead Review" -- anywhere in the
                             path). Loose charts on a COMPLETE board are
                             final anyway; on a live board you pick one
                             stage for all of them (default_stage).
  query.xlsx              -> the SharePoint "Export to Excel" file listing
  query*.iqy              -> the web query beside it (site host + PDA root)
  other workbooks         -> content-sniffed, classified by what's inside
                             (filenames lie; the workbook cells rule)

The only thing written next to your files is a small `_manifest.json`
(underscore-prefixed = never parsed as PDA data). State and month/year
default from the Table A itself -- press Enter through the prompts.
"""
from __future__ import annotations

import calendar
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ask(prompt, default=None):
    tail = f" [{default}]" if default not in (None, "") else ""
    val = input(f"{prompt}{tail}: ").strip().strip('"').strip("'")
    return val or (default or "")


def ask_yn(prompt, default=True):
    d = "Y/n" if default else "y/N"
    val = input(f"{prompt} ({d}): ").strip().lower()
    if not val:
        return default
    return val.startswith("y")


def pick_folder():
    """Windows folder-picker (tkinter). Returns "" if unavailable/cancelled."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(
            title="Pick your PDA folder (the downloaded SharePoint folder)")
        root.destroy()
        return path or ""
    except Exception:
        return ""


# OpenFEMA spells the state out in PublicAssistanceFundedProjectsSummaries
STATE_NAMES = {"IL": "Illinois", "IN": "Indiana", "MI": "Michigan",
               "MN": "Minnesota", "OH": "Ohio", "WI": "Wisconsin"}


def refresh_history(state):
    """Optional prior-FEMA-history refresh — best-effort, NEVER fatal."""
    name = STATE_NAMES.get(state) or ask(
        "  Full state name as OpenFEMA spells it", state)
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, str(HERE / "build_history.py"),
             "--state", state, "--state-name", name],
            cwd=str(HERE), timeout=900)
        if r.returncode != 0:
            print("  !! history refresh failed -- keeping the existing snapshot")
    except Exception as e:
        print(f"  !! history refresh skipped ({type(e).__name__}) -- "
              "keeping the existing snapshot")


def scan(folder: Path):
    """Classify everything in the folder: filename first, content-sniff for
    workbooks whose name says neither Table A nor Chart A."""
    import sp_filetree as sp
    from chart_a_parser import sniff_workbook

    found = {"table_a": [], "chart_a": [], "query": [], "iqy": [], "other": []}
    stages = {}          # chart path -> stage from its folder location
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or p.name.startswith("~$"):
            continue
        rel = p.relative_to(folder)
        if any(part.startswith("_") for part in rel.parts[:-1]):
            continue     # _-prefixed folders are aside material, never parsed
        suf = p.suffix.lower()
        name_l = p.name.lower()
        if suf == ".iqy":
            found["iqy"].append(p)
        elif suf == ".xlsx" and name_l.startswith("query"):
            found["query"].append(p)
        elif suf in (".xlsx", ".xlsm"):
            if "table a" in name_l or "tablea" in name_l:
                kind = "table_a"
            elif sp.looks_like_chart_a(p.name):
                kind = "chart_a"
            else:
                try:
                    kind = sniff_workbook(p) or "other"
                except Exception:
                    kind = "other"
            found[kind if kind in found else "other"].append(p)
            if kind == "chart_a":
                stages[p] = sp.stage_from_segments(list(rel.parts[:-1]))[0]
    return found, stages


def table_a_defaults(paths):
    """(state_code, 'Month Year', 'MM.DD.YYYY - MM.DD.YYYY') read from the
    newest Table A, best-effort. The month/year is the PDA's month (meta
    `pda_start` — what the PDA is named for), falling back to the incident
    start month only when the workbook doesn't carry a PDA start."""
    if not paths:
        return None, None, None
    from chart_a_parser import parse_table_a
    p = max(paths, key=lambda x: x.stat().st_mtime)
    try:
        meta = parse_table_a(p).meta
    except Exception:
        return None, None, None
    st = (meta.get("state_code") or "").strip().upper()[:2] or None

    def month_year(iso):
        try:
            return f"{calendar.month_name[int(iso[5:7])]} {int(iso[:4])}"
        except (TypeError, ValueError, IndexError):
            return None

    def mdy(iso):
        try:
            return f"{iso[5:7]}.{iso[8:10]}.{iso[:4]}"
        except (TypeError, IndexError):
            return None

    my = month_year(meta.get("pda_start")) or month_year(meta.get("incident_start"))
    a, b = mdy(meta.get("incident_start")), mdy(meta.get("incident_end"))
    period = f"{a} - {b}" if a and b else (a or None)
    return st, my, period


def main():
    print("=" * 62)
    print("PDA Board build wizard -- point it at your PDA folder")
    print("=" * 62)
    print("Give it the folder you downloaded from SharePoint (the whole PDA")
    print("folder / Final Products, or just a folder of Chart A's). It reads")
    print("the files where they are -- nothing is moved or copied.\n")

    # -- the folder (browse window by default; pasting still works) ------
    raw = sys.argv[1] if len(sys.argv) > 1 else ""
    while True:
        if not raw:
            raw = input("Your PDA folder -- press Enter to BROWSE, or paste a "
                        "path: ").strip().strip('"').strip("'")
            if not raw:
                print("  (a folder-picker window is opening -- it may appear "
                      "behind this one)")
                raw = pick_folder()
                if not raw:
                    print("  !! no folder picked")
                    continue
        folder = Path(raw)
        if folder.is_dir():
            break
        print(f"  !! not a folder: {folder}")
        raw = ""

    print("\nReading the folder ...")
    found, stages = scan(folder)
    import sp_filetree as sp

    # the SharePoint query files often sit one level UP from where the
    # workbooks were piled (e.g. you pointed at ".../WI 2026 Chart A" while
    # "query WI 2026.iqy" lives beside that folder) — offer them
    iqy_path = None
    if not found["iqy"]:
        up = sorted(folder.parent.glob("*.iqy"))
        if up and ask_yn(f"\nFound {up[0].name} one level up ({folder.parent.name}) -- "
                         "use it for the SharePoint links?", True):
            iqy_path = up[0]
    n_ch = len(found["chart_a"])
    print(f"  Chart A's ............ {n_ch}")
    if n_ch:
        by_stage = {}
        for p, s in stages.items():
            by_stage[s] = by_stage.get(s, 0) + 1
        for s in sorted(by_stage, reverse=True):
            lbl = sp.STAGE_LABELS[s] if s else "loose (no stage folder in path)"
            print(f"      {by_stage[s]:>3}  {lbl}")
    for p in found["table_a"]:
        print(f"  Table A .............. {p.name}")
    print(f"  query.xlsx export .... {found['query'][0].name if found['query'] else 'none'}")
    print(f"  query.iqy (links) .... "
          f"{found['iqy'][0].name if found['iqy'] else (iqy_path.name + ' (from the parent folder)' if iqy_path else 'none')}")
    if found["other"]:
        print(f"  other workbooks ...... {len(found['other'])} (ignored by the board)")
    if not found["table_a"]:
        print("\n  !! No Table A found. The board's indicators (state/county")
        print("     thresholds) come from the Table A -- without one the build")
        print("     runs but flags NO_TABLE_A / NO_STATE_INDICATOR.")
    if not (found["table_a"] or found["chart_a"]):
        print("  !! Nothing to build from here.")
        if not ask_yn("Continue anyway?", False):
            sys.exit(1)

    # -- Table A choice (a drop can carry several copies/variants — e.g. a
    # full one AND a "Counties That Met Threshold Only" cut. The board's
    # dollars and indicators come from ONE of them; the user must say which)
    ta_pick = found["table_a"][0] if found["table_a"] else None
    if len(found["table_a"]) > 1:
        print("\n  Multiple Table A workbooks found. The board's indicators and")
        print("  county figures come from ONE master -- pick which:")
        newest = max(found["table_a"], key=lambda p: p.stat().st_mtime)
        for i, p in enumerate(found["table_a"], 1):
            mt = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
            star = "  <- newest" if p == newest else ""
            print(f"    {i}. {p.relative_to(folder)}  (modified {mt}){star}")
        default_n = str(found["table_a"].index(newest) + 1)
        while True:
            v = ask("  Use Table A #", default_n)
            if v.isdigit() and 1 <= int(v) <= len(found["table_a"]):
                ta_pick = found["table_a"][int(v) - 1]
                break
            print("    !! enter one of the numbers listed")

    # -- identity (defaults read from the chosen Table A itself) ---------
    ta_state, ta_my, ta_period = table_a_defaults([ta_pick] if ta_pick else [])
    if ta_state or ta_my or ta_period:
        print(f"\nRead from the Table A: state={ta_state or '?'}, "
              f"PDA month={ta_my or '?'}"
              f"{f', incident period {ta_period}' if ta_period else ''}"
              " -- press Enter to accept.")
    state = ask("State (2-letter)", ta_state or "IN").upper()[:2]
    month_year = ask("PDA month + year (for the id/title)", ta_my or "May 2026")
    pda_id = ask("PDA id (just a folder/file naming slug -- default is fine)",
                 f"{state}_PDA_{month_year.replace(' ', '_')}")
    title = ask("Title", f"{state} PA PDA - {month_year}")
    complete = ask_yn("COMPLETE (final figures) board?", True)
    met_only = complete and ask_yn(
        "met_only -- show only counties that met their indicator?", True)

    # content switches -- answer No to strip things for external sharing
    # (e.g. sending the board to the state). Stripped at BUILD: the HTML
    # genuinely does not carry the data.
    print("\n  Content switches (Enter = include, n = strip from the board):")
    inc_links = ask_yn("  Include SharePoint links? (file tree, folder/"
                       "Chart A/Table A links)", True)
    inc_histd = ask_yn("  Include historical PA obligation dollars? (prior "
                       "applicants + declarations always stay)", True)
    inc_insp = ask_yn("  Include inspector names?", True)

    # optional: refresh the prior-FEMA-history snapshot (static — it only
    # changes when this is run). Default NO; any failure is skipped.
    if ask_yn("Refresh the prior-FEMA-history snapshot from OpenFEMA now? "
              "(needs internet)", False):
        refresh_history(state)

    dim = HERE / "data" / f"dim_county_{state.lower()}.csv"
    if not dim.exists():
        print(f"\n  !! No county reference data for '{state}' "
              f"(data/dim_county_{state.lower()}.csv). The six Region 5 states "
              f"ship ready-made; other states need build_dim_county.py first.")
        if not ask_yn("Continue anyway?", False):
            sys.exit(1)

    # -- manifest --------------------------------------------------------
    manifest = {
        "pda_id": pda_id, "title": title, "state": state,
        "sharepoint_base": "", "stale_hours": 876000 if complete else 48,
        "events": [],
    }
    if len(found["table_a"]) > 1 and ta_pick:
        # pin the user's choice — otherwise the pipeline takes newest-modified
        manifest["table_a"] = ta_pick.relative_to(folder).as_posix()
    if not inc_links:
        manifest["no_links"] = True
    if not inc_histd:
        manifest["history_no_dollars"] = True
    if not inc_insp:
        manifest["no_inspectors"] = True
    if complete:
        manifest["complete"] = True
        manifest["met_only"] = met_only
        manifest["master_folder"] = ""
    else:
        manifest["stale_hours"] = 48
        loose = sum(1 for s in stages.values() if s == 0)
        if loose:
            print(f"\n  {loose} Chart A('s) sit in no stage folder. On a live")
            print("  board a chart's stage is its folder -- for these loose")
            print("  ones, pick the stage they are actually at:")
            print("    2 = For PDA Lead Review   3 = Ready for Table A")
            print("    4 = Entered in Table A    (blank = leave as Not submitted)")
            ds = ask("  Stage for the loose Chart A's", "")
            if ds in ("2", "3", "4"):
                manifest["default_stage"] = int(ds)
        evs = ask("Incident period label(s), ';'-separated (live PDA only)", "")
        manifest["events"] = [{"event_id": f"E{i+1}", "label": e.strip()}
                              for i, e in enumerate(evs.split(";")) if e.strip()]

    mpath = folder / "_manifest.json"   # _-prefixed: never parsed as PDA data
    try:
        mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError:
        mpath = HERE / "drops" / f"{pda_id}_manifest.json"
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"  (folder not writable -- manifest kept at {mpath})")
    print(f"\nManifest written: {mpath}")

    # -- build -----------------------------------------------------------
    out = Path(ask("Output folder", str(HERE / f"out_{pda_id.lower()}")))
    if ask_yn("Build the board now?", True):
        import pipeline
        m = pipeline.load_manifest(mpath)
        pipeline.build(folder, m, out, iqy_path=iqy_path)
        print(f"\nDone: {out / 'board.html'}  (one self-contained file -- "
              f"open it directly or email it)")
        print("Dropped more files into the folder? Just re-run:")
    else:
        print("\nTo build when ready:")
    iqy_flag = f' --iqy "{iqy_path}"' if iqy_path else ""
    print(f'  python pipeline.py --drop "{folder}" --manifest "{mpath}" --out "{out}"{iqy_flag}')


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n(cancelled -- nothing else written)")
