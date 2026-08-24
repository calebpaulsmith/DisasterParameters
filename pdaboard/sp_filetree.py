"""SharePoint file-tree intelligence for PDA Board.

Input: ``query.xlsx`` — SharePoint's "Export to Excel" of the PDA document
library (columns Name / Modified / Modified By / File Size / Item Type / Path).

Companion input: ``query*.iqy`` — the little text file SharePoint hands you
*with* that export (Excel opens it to build query.xlsx). It carries no rows,
but it does carry the two things the export drops: the **site host** and the
**RootFolder** of the PDA library folder. Those are exactly the pieces needed
to turn the export's server-relative ``Path`` column into working links, so
:func:`parse_iqy` is the canonical source of a PDA's SharePoint links (see
``resolve_links`` in pipeline.py, and the board's Admin -> SharePoint links
panel, which parses the same file in the browser to swap PDAs).

This module owns the **four-stage validation model** — the stage of a Chart A
is *where it sits* in the SharePoint folder workflow:

    1  Working             Damage Data/Counties/<County>/          (field copies)
    2  For PDA Lead Review Damage Data/Chart A's/1. For PDA Lead Review/
                           (plus loose files at the Chart A's root)
    3  Ready for Table A   Damage Data/Chart A's/2. Ready for Table A/
                           (a local "Validated" folder ranks the same)
    4  Entered in Table A  .../2. Ready for Table A/Entered in Table A/

and the **matching trick** that makes manual volume drops work: a dropped file
loses its SharePoint folder context, so we recover stage / modified / author /
URL by matching the dropped filename (size as tiebreaker) back to the export.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import quote, unquote, urlsplit

import openpyxl

STAGE_LABELS = {
    0: "Not started",
    1: "Working",
    2: "For PDA Lead Review",
    3: "Ready for Table A",
    4: "Entered in Table A",
}

# (lowercased folder-segment, rank). A path's stage is the MAX rank among
# matching segments — 'Entered in Table A' paths also contain '2. Ready for
# Table A', and everything in the pipeline contains "Chart A's".
DEFAULT_FOLDER_STAGES = [
    ("entered in table a", 4),
    ("2. ready for table a", 3),
    ("validated", 3),
    ("1. for pda lead review", 2),
    ("chart a's", 2),
    ("chart as", 2),          # apostrophe-less variant seen in local drops
    ("counties", 1),
]

# Where county working folders live under a PDA's SharePoint root. Region 5's
# PDA libraries all use this shape (verified in the IN export); it is only ever
# an ASSUMPTION when there is no query.xlsx to confirm it — flagged as such so
# the board's Admin panel can say so and the lead can correct it in place.
COUNTY_SUBPATH = "Damage Data/Counties"

CHART_A_NAME_RE = re.compile(r"chart\s*a", re.I)
# 'Decatur - Indiana (June 6 - 11, 2026).xlsx' — county-dash-state pattern
DASH_STATE_RE = re.compile(r"^[A-Za-z .'\-]+ - [A-Za-z .]+ \(")


@dataclass
class FileRow:
    name: str
    path: str                 # SharePoint folder path (no leading slash)
    item_type: str            # "Item" | "Folder"
    modified: Optional[str]   # ISO string
    modified_by: str
    size: Optional[int]
    stage: int = 0
    stage_basis: Optional[str] = None
    county_folder: Optional[str] = None

    @property
    def is_item(self) -> bool:
        return self.item_type.lower() == "item"

    @property
    def full_path(self) -> str:
        return f"{self.path}/{self.name}" if self.path else self.name

    @property
    def segments(self) -> list:
        return [s for s in self.path.split("/") if s]

    def url(self, base: str) -> Optional[str]:
        if not base:
            return None
        return base.rstrip("/") + "/" + quote(self.full_path)


def stage_from_segments(segments, folder_stages=None):
    """(rank, basis_segment) for a path — MAX rank among matching segments."""
    folder_stages = folder_stages or DEFAULT_FOLDER_STAGES
    low = [s.lower() for s in segments]
    best, basis = 0, None
    for seg_name, rank in folder_stages:
        if seg_name in low and rank > best:
            best, basis = rank, seg_name
    return best, basis


def county_folder_of(segments) -> Optional[str]:
    """Folder name directly under 'Counties' ('REMCs' passes through as-is)."""
    low = [s.lower() for s in segments]
    if "counties" in low:
        i = low.index("counties")
        if i + 1 < len(segments):
            return segments[i + 1]
    return None


def norm_county_name(s) -> str:
    """Fuzzy county join key: lowercased, punctuation/space-insensitive,
    'Saint' -> 'St', trailing 'County' dropped — so a hand-typed Counties/
    folder ('St Joseph', 'DE KALB', 'Lake County') still attaches to the
    workbook's own county name ('St. Joseph', 'DeKalb', 'Lake')."""
    s = re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("saint "):
        s = "st " + s[6:]
    if s.endswith(" county"):
        s = s[: -len(" county")]
    return s.replace(" ", "")


def looks_like_chart_a(name: str) -> bool:
    n = name.strip()
    if not n.lower().endswith(".xlsx") or n.startswith("~$"):
        return False
    return bool(CHART_A_NAME_RE.search(n) or DASH_STATE_RE.match(n))


# ------------------------------------------------------------- query*.iqy
# The SharePoint web-query file. Two forms of the same facts (a URL line plus
# key=value lines); we read both and prefer the explicit keys.

def sp_quote(path: str) -> str:
    """Percent-encode a SharePoint path, keeping the separators."""
    return quote(path, safe="/")


def parse_iqy(text: str) -> dict:
    """Site host + RootFolder out of a SharePoint ``.iqy`` web query.

    Returns ``{host, root_path, root_name, root_url, sharepoint_base,
    master_folder, master_folder_assumed, list_id, view_id}`` — every value
    None/absent when the file doesn't carry it (never guessed from thin air).
    ``sharepoint_base`` is the bare host, which is what the export's
    server-relative ``Path`` column needs prepended.
    """
    url, kv = None, {}
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if url is None and ln.lower().startswith("http"):
            url = ln
            continue
        if "=" in ln:
            k, v = ln.split("=", 1)
            kv[k.strip().lower()] = v.strip()

    root = kv.get("rootfolder") or ""
    if not root and url:
        m = re.search(r"[?&]RootFolder=([^&]*)", url, re.I)
        root = m.group(1) if m else ""

    app = kv.get("sharepointapplication") or url or ""
    host = ""
    if app:
        parts = urlsplit(app)
        if parts.scheme and parts.netloc:
            host = f"{parts.scheme}://{parts.netloc}"

    root_path = unquote(root).strip().rstrip("/")
    if root_path and not root_path.startswith("/"):
        root_path = "/" + root_path

    root_url = f"{host}{sp_quote(root_path)}" if host and root_path else None
    return {
        "host": host or None,
        "root_path": root_path or None,
        "root_name": root_path.rsplit("/", 1)[-1] if root_path else None,
        "root_url": root_url,
        "sharepoint_base": host or None,
        "master_folder": (f"{root_url}/{sp_quote(COUNTY_SUBPATH)}" if root_url else None),
        "master_folder_assumed": bool(root_url),
        "list_id": kv.get("sharepointlistname"),
        "view_id": kv.get("sharepointlistview"),
    }


def load_iqy(path) -> dict:
    """parse_iqy() over a file (.iqy files are plain text, occasionally ANSI)."""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    out = parse_iqy(text)
    out["source"] = Path(path).name
    return out


def find_query_iqy(drop: Path):
    """The newest ``*.iqy`` in the drop (``_``-prefixed aside folders skipped)."""
    hits = [p for p in drop.rglob("*.iqy")
            if not p.name.startswith("~$")
            and not any(part.startswith("_") for part in p.relative_to(drop).parts[:-1])]
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def root_path_from_rows(rows) -> Optional[str]:
    """The PDA's own library folder — the SHORTEST path in the export."""
    paths = [r.path for r in rows if r.path]
    return "/" + min(paths, key=lambda p: (len(p.split("/")), len(p))) if paths else None


# ------------------------------------------------ master (multi-PDA) exports
# One export / one .iqy can cover the whole "Ongoing PDA's" library rather than
# a single PDA. Then the root is a PARENT and every PDA is a folder under it —
# so the root has to be narrowed to THIS PDA before any of it means anything
# (otherwise scope, stages and links silently mix PDAs).

PDA_MARKERS = ("damage data", "chart a's", "chart as", "counties")


def pda_root_candidates(rows) -> list:
    """Server-relative paths of every PDA folder visible in an export.

    A PDA folder is whatever sits directly above the first workflow segment
    (``Damage Data`` / ``Chart A's`` / ``Counties``). A single-PDA export
    yields exactly one; a library-wide export yields one per PDA, busiest
    first.
    """
    hits = {}
    for r in rows:
        segs = r.segments
        for i, s in enumerate(s.lower() for s in segs):
            if s in PDA_MARKERS and i > 0:
                hits["/" + "/".join(segs[:i])] = hits.get("/" + "/".join(segs[:i]), 0) + 1
                break
    return sorted(hits, key=lambda p: (-hits[p], p))


def filter_rows_under(rows, root_path: str) -> list:
    """Only the rows inside ``root_path`` (the chosen PDA's subtree)."""
    pref = root_path.strip("/") + "/"
    return [r for r in rows if (r.path + "/").startswith(pref) or r.path == root_path.strip("/")]


def _pda_tokens(text: str) -> set:
    return {t for t in re.split(r"[^A-Za-z0-9]+", (text or "").lower()) if t}


def pda_identity_tokens(manifest: dict) -> set:
    """The words that identify a PDA: state, month, year (from id/title)."""
    toks = _pda_tokens(f"{manifest.get('pda_id','')} {manifest.get('title','')}")
    toks |= _pda_tokens(manifest.get("state") or "")
    # 'pda'/'pa' appear in every folder name — useless for telling PDAs apart
    return toks - {"pda", "pa", "the", "and"}


def match_pda_folder(candidates, manifest) -> Optional[str]:
    """Pick the candidate whose folder name matches this PDA's identity.

    Scored on shared tokens (state + month + year); a tie or a zero score
    returns None — the caller flags it rather than guessing.
    """
    want = pda_identity_tokens(manifest)
    if not want or not candidates:
        return None
    scored = sorted(((len(want & _pda_tokens(c.rsplit("/", 1)[-1])), c) for c in candidates),
                    key=lambda x: (-x[0], x[1]))
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None                      # ambiguous — two folders match equally
    return scored[0][1]


def looks_like_pda_folder(name: str, manifest: dict) -> bool:
    """Does this folder NAME look like this PDA (vs. a parent library folder)?"""
    return bool(pda_identity_tokens(manifest) & _pda_tokens(name or ""))


def counties_path_from_rows(rows) -> Optional[str]:
    """The export's REAL counties folder (a folder row sitting right under it)."""
    for r in rows:
        segs = r.segments
        if not r.is_item and segs and segs[-1].lower() == "counties":
            return "/" + r.path
    return None


def load_filetree(query_xlsx, folder_stages=None) -> list:
    """Parse query.xlsx into FileRow records with stage + county derived."""
    wb = openpyxl.load_workbook(query_xlsx, data_only=True, read_only=True)
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    header = [str(h or "").strip().lower() for h in next(rows_iter)]

    def col(label):
        try:
            return header.index(label)
        except ValueError:
            raise ValueError(f"query.xlsx missing column {label!r}; got {header}")

    i_name, i_mod, i_by = col("name"), col("modified"), col("modified by")
    i_size, i_type, i_path = col("file size"), col("item type"), col("path")

    out = []
    for raw in rows_iter:
        if raw is None or all(v in (None, "") for v in raw):
            continue
        name = str(raw[i_name] or "").strip()
        if not name:
            continue
        mod = raw[i_mod]
        size = raw[i_size]
        fr = FileRow(
            name=name,
            path=str(raw[i_path] or "").strip().strip("/"),
            item_type=str(raw[i_type] or "").strip(),
            modified=(mod.isoformat(sep=" ") if hasattr(mod, "isoformat")
                      else (str(mod).strip() or None)),
            modified_by=str(raw[i_by] or "").strip(),
            size=int(size) if isinstance(size, (int, float)) and size else None,
        )
        fr.stage, fr.stage_basis = stage_from_segments(fr.segments, folder_stages)
        fr.county_folder = county_folder_of(fr.segments)
        out.append(fr)
    wb.close()
    return out


def scope_counties(rows) -> list:
    """County folder names directly under Counties/ (the PDA's scope list)."""
    seen, out = set(), []
    for r in rows:
        if not r.is_item and r.county_folder is None and r.segments:
            # a Folder row whose OWN name sits directly under Counties/
            if r.segments and r.segments[-1].lower() == "counties":
                if r.name not in seen:
                    seen.add(r.name)
                    out.append(r.name)
    return out


def match_dropped_file(filename: str, size: Optional[int], rows) -> dict:
    """Match a dropped file back to its filetree row.

    Returns {row, method, flags[]}:
      method: 'name_unique' | 'name_size' | 'ambiguous_highest_stage' | 'unmatched'
    """
    cands = [r for r in rows if r.is_item and r.name.lower() == filename.lower()]
    flags = []
    if not cands:
        return {"row": None, "method": "unmatched", "flags": ["UNMATCHED_DROP"]}
    if len(cands) == 1:
        row = cands[0]
        if size is not None and row.size is not None and row.size != size:
            flags.append("SIZE_MISMATCH")  # re-saved since export; name is unique, accept
        return {"row": row, "method": "name_unique", "flags": flags}
    if size is not None:
        by_size = [r for r in cands if r.size == size]
        if len(by_size) == 1:
            return {"row": by_size[0], "method": "name_size", "flags": flags}
        if by_size:
            cands = by_size
    # same name (and size) in several folders — the duplicate-across-stages
    # case. Canonical rule: highest stage wins; tie -> latest modified.
    cands.sort(key=lambda r: (r.stage, r.modified or ""), reverse=True)
    flags.append("AMBIGUOUS_MATCH")
    return {"row": cands[0], "method": "ambiguous_highest_stage", "flags": flags}
