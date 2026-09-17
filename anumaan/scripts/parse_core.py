"""Pure-stdlib parsing core for ANUMAAN.

This module contains every transform that does NOT need pdfplumber. It is
deliberately dependency-free so:

  * `make test` can run with only Python's standard library + bs4 installed
    (P1 acceptance criterion),
  * unit tests can construct minimal Python objects and exercise the full
    parsing pipeline without a real PDF in the room.

If you import this module you can prove the parser logic in isolation; for
the pdfplumber adapter (open a PDF, walk pages, hand cells to the core)
see scripts/parse_report.py.

The two eras are detected from summary text and dispatched to different
row parsers because the column layout changed when PAIMANA replaced OCMS
in September 2025:

  OCMS era (through FY 2024-25) - 13 columns:
    Sl.No, Project(name+agency+code), Date of Approval, Original Cost,
    Revised Cost, Anticipated Cost, Cumulative Expenditure, Original DoC,
    Revised DoC, Anticipated DoC, Time Overrun (months), Cost Overrun (%),
    Reasons for Delay.

  PAIMANA era (FY 2025-26 onward) - 10 columns:
    Sl.No, Project(name+agency+project_code+legacy_ocms+pmgid), State,
    Date of Approval, Original DoC, Target DoC, Original Cost, Revised Cost,
    Cumulative Expenditure, Physical Progress (%).
    Anticipated cost, time overrun, cost overrun, and reasons for delay
    are NOT carried - those fields are returned as None on parsed rows
    so the schema is uniform across eras.
"""
from __future__ import annotations

import datetime
import re
from typing import Callable, Iterable

NUM = r"([\d,]+(?:\.\d+)?)"

# ---------------------------------------------------------------------------
# Numeric and date helpers
# ---------------------------------------------------------------------------

def to_float(s) -> float | None:
    """Parse a numeric cell that may include currency markers, commas, and
    footnote markers. Returns None on any failure - never raises.

    Strategy: extract the first run of digits/commas/decimal/sign from the
    cell, ignoring rupee markers, footnote asterisks, embedded "Rs.", "(#)",
    and similar noise. Strips the unicode "−" minus and Indian-accounting
    "(-)" convention.
    """
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    # Normalise Indian-accounting "(-)N" -> "-N", and unicode minus "−" -> "-"
    t = t.replace("−", "-")
    t = re.sub(r"\(\-\)", "-", t)
    # Pull out the first run that looks like a number; everything else is noise.
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", t)
    if not m:
        return None
    raw = m.group(0)
    try:
        v = float(raw.replace(",", ""))
    except ValueError:
        return None
    if v != v:  # NaN guard
        return None
    return v


def to_int(s) -> int | None:
    v = to_float(s)
    return int(v) if v is not None else None


def parse_date(s) -> str | None:
    """Normalise a date string to ISO YYYY-MM-DD if possible.

    Returns the canonical string, or None if the value is missing/sentinel.
    Sentinels observed in the wild (per docs/data-quality-rules.md DQ001/DQ002):
    '', 'NA', 'N.A.', '01/1900', '01-01-1900', 'Not Available', '-'.

    Patterns supported:
      yyyy-mm-dd, dd/mm/yyyy, dd-mm-yyyy, dd/mm/yy, mm/yyyy,
      dd-Mon-yyyy ("31-Mar-2027").
    Returns None for unrecognised formats rather than fabricating.
    """
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    if t.upper() in {"NA", "N.A.", "N/A", "NOT AVAILABLE", "-"}:
        return None
    # Sentinels must be matched BEFORE generic pattern matching, otherwise
    # '01/1900' parses as January 1900 instead of being treated as missing.
    if re.match(r"^0?1[/\-]0?1[/\-]?1900$", t):
        return None
    if re.match(r"^0?1[/\-]1900$", t):
        return None
    # Build a list of (pattern, builder) so we can also validate ranges.
    MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
              "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    patterns: list[tuple[str, Callable]] = [
        (r"^(\d{4})-(\d{1,2})-(\d{1,2})$",
         lambda g: f"{int(g[0]):04d}-{int(g[1]):02d}-{int(g[2]):02d}"),
        (r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$",
         lambda g: f"{int(g[2]):04d}-{int(g[1]):02d}-{int(g[0]):02d}"),
        (r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})$",
         lambda g: f"{(2000 + int(g[2])) if int(g[2]) < 70 else (1900 + int(g[2])):04d}-{int(g[1]):02d}-{int(g[0]):02d}"),
        (r"^(\d{1,2})[/\-](\d{4})$",
         lambda g: f"{int(g[1]):04d}-{int(g[0]):02d}-01"),
        (r"^(\d{1,2})[-\s]([A-Za-z]{3,})[-\s](\d{4})$",
         lambda g: f"{int(g[2]):04d}-{MONTHS.get(g[1].lower()[:3], 0):02d}-{int(g[0]):02d}"),
    ]
    for pat, build in patterns:
        m = re.match(pat, t)
        if not m:
            continue
        out = build(m.groups())
        # Validate that the assembled date is real (catches 2026-02-31 etc.)
        try:
            y, mo, d = (int(x) for x in out.split("-"))
            datetime.date(y, mo, d)
            return out
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# Summary parsing (era detection)
# ---------------------------------------------------------------------------

def parse_summary(text: str) -> dict:
    """Pull headline figures from either era's summary page.

    Always returns the full key set with `None` for missing values. Callers
    can rely on `.get()` returning None rather than KeyError.
    """
    flat = re.sub(r"\s+", " ", text or "")
    out: dict = {
        "era": None,
        "projects_on_monitor": None,
        "projects_delayed": None,
        "original_cost_cr": None,
        "revised_cost_cr": None,
        "anticipated_cost_cr": None,
        "cost_overrun_cr": None,
        "cost_overrun_pct": None,
        "expenditure_cr": None,
        "expenditure_pct_of_revised": None,
    }

    # The "Total original cost" sentence in real OCMS flash reports reads:
    #   "Total original cost of these 1623 projects is 19,33,390.22 crore"
    # The embedded project count and the word "is" sit between the anchor
    # and the number we want. We anchor on the verb "is" (or "likely to be")
    # to stop the optional group from chewing through later "crore" mentions.
    ocms_total = re.search(r"status of the\s*" + NUM + r"\s*Central Sector", flat, re.I)
    ocms_delayed = re.search(NUM + r"\s*projects are delayed", flat, re.I)
    ocms_overrun = re.search(r"cost overruns? of\s*" + NUM + r"\s*crore\s*\(" + NUM + r"\s*%", flat, re.I)
    ocms_orig = re.search(
        r"Total original cost\b[^.]{0,200}?(?:is|likely to be)\s*"
        + NUM + r"\s*crore",
        flat, re.I,
    )
    ocms_antic = re.search(
        r"anticipated completion cost\b[^.]{0,200}?(?:is|likely to be)\s*"
        + NUM + r"\s*crore",
        flat, re.I,
    )

    if ocms_total or ocms_delayed:
        out["era"] = "ocms"
        out["projects_on_monitor"] = int(to_float(ocms_total.group(1))) if ocms_total else None
        out["projects_delayed"] = int(to_float(ocms_delayed.group(1))) if ocms_delayed else None
        out["original_cost_cr"] = to_float(ocms_orig.group(1)) if ocms_orig else None
        out["anticipated_cost_cr"] = to_float(ocms_antic.group(1)) if ocms_antic else None
        if ocms_overrun:
            out["cost_overrun_cr"] = to_float(ocms_overrun.group(1))
            out["cost_overrun_pct"] = to_float(ocms_overrun.group(2))
        return out

    pai_ongoing = re.search(NUM + r"\s*\|\s*\d+\s*Ongoing Projects", flat)
    pai_orig = re.search(r"([\d,]+)\s*Original Cost", flat)
    pai_rev = re.search(r"([\d,]+)\s*Revised Cost", flat)
    pai_exp = re.search(r"([\d,]+)\s*\(" + NUM + r"%\s*of Revised Cost\)", flat)
    if pai_ongoing or pai_orig:
        out["era"] = "paimana"
        out["projects_on_monitor"] = int(to_float(pai_ongoing.group(1))) if pai_ongoing else None
        out["original_cost_cr"] = to_float(pai_orig.group(1)) if pai_orig else None
        out["revised_cost_cr"] = to_float(pai_rev.group(1)) if pai_rev else None
        if pai_exp:
            out["expenditure_cr"] = to_float(pai_exp.group(1))
            out["expenditure_pct_of_revised"] = to_float(pai_exp.group(2))
    return out


# ---------------------------------------------------------------------------
# Bracketed ID extraction
# ---------------------------------------------------------------------------

OCMS_EXPECTED_COLS = 13
PAIMANA_EXPECTED_COLS = 10

# Known-agency acronyms are explicitly NOT IDs. Without this list, the
# position-from-the-right heuristic promoted e.g. "(NHAI)" into the
# legacy_ocms_code slot and merged every NHAI project across the era
# boundary into a single entity. Provenance: review finding 7, 16 Sep 2026.
KNOWN_AGENCY_ACRONYMS = {
    "nhai", "nra", "nrc", "morth", "mor th", "mor", "nr", "rly", "rail",
    "railways", "moes", "moesr", "mowr", "punjab", "haryana", "up", "uk",
    "moha", "mah", "kerala", "tn", "tamil nadu", "kar", "karnataka",
    "aai", "aerca", "apdrp", "bbnl", "bcpl", "bescom", "bhakra", "bhilwara",
    "bmtc", "bnh", "bpscl", "bsnl", "ccl", "cel", "central", "cer",
    "cfcl", "cgl", "chardham", "chardham Pariyojana", "chennai",
    "cmd", "coal", "cpwd", "cr", "dda", "delhi", "dfcc", "dfccil",
    "dha", "dmrc", "dvc", "eastern", "ecil", "ecl", "gaon", "gas",
    "gail", "gmr", "gvk", "hccl", "hind", "hindustan", "hll", "hpcl",
    "hudco", "iocl", "ir", "irb", "ircon", "itd", "jica", "jk", "kashmir",
    "kendriya", "kh", "kochi", "krc", "krcl", "kudremukh", "l&t", "lnct",
    "madhya", "mahanadi", "mci", "mecl", "meja", "ministry", "moef",
    "moefcc", "moh", "mohfw", "mopng", "mop", "mor", "morth", "mowr",
    "mpeb", "mp", "mppkvv", "mpsedc", "mpsrtc", "mrvc", "mumbai", "nabh",
    "nabh Nirman", "nagar", "nagpur", "narmada", "nbcc", "nci", "ncrtc",
    "ncti", "ner", "new", "nh", "nhai", "nhdc", "nhsrcl", "nilgiri",
    "nlc", "nmdc", "noida", "north", "npcil", "npccl", "nrl", "nuclear",
    "ongc", "ordnance", "patna", "pdd", "petroleum", "pfc", "pgcil",
    "phed", "pipeline", "pmc", "pmg", "pnb", "port", "power", "pr",
    "project", "pspcl", "pun", "punjab", "pwd", "railway", "railways",
    "rajasthan", "rajdhani", "ramky", "ranchi", "rdd", "reliance", "res",
    "rew", "rfcl", "ril", "rites", "river", "rldav", "roads", "rohtak",
    "roukela", "rrts", "rs", "rural", "rvnl", "sasan", "satluj", "sbi",
    "seci", "sector", "south", "southern", "spl", "stables", "steel",
    "surat", "tata", "telecom", "thermal", "thdc", "tn", "transmission",
    "udaipur", "ugcl", "uhbvn", "uk", "up", "urban", "uttar", "vadodara",
    "vizag", "vyasi", "wapcos", "water", "wccl", "wef", "west", "western",
    "wris", "yelluru",
}


def _looks_like_id(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    low = s.lower()
    if any(low.startswith(p) for p in ("pmg", "omc", "ocms", "p-", "proj",
                                       "pg-", "pmg-", "omc-", "ocms-", "id-")):
        return True
    if any(ch.isdigit() for ch in s):
        return True
    return False


def _looks_like_agency(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    low = s.lower()
    if low in KNOWN_AGENCY_ACRONYMS:
        return True
    if 2 <= len(s) <= 6 and s == s.upper() and s.isalpha():
        return True
    return False


def _extract_id_from_ocms_project(text: str) -> dict:
    """Pull (project_name, agency, code) out of the OCMS-era project cell.

    Observed shape: "<project name>(<agency>)(<code>)". The rightmost paren
    group that contains a digit is treated as the code; the next one to its
    left, if it looks like an agency, is the agency; everything else is the
    project name.
    """
    raw = (text or "").strip()
    name, agency, code = raw, None, None
    matches = re.findall(r"\(([^()]*)\)", raw)
    if not matches:
        return {"project_name": raw or None, "agency": None, "code": None}
    # Find the rightmost paren group that looks like an ID code.
    code_idx = None
    for i in range(len(matches) - 1, -1, -1):
        if _looks_like_id(matches[i]):
            code_idx = i
            break
    if code_idx is not None:
        code = matches[code_idx].strip()
        # Agency is the paren group immediately to the left, if it looks like one.
        if code_idx - 1 >= 0 and _looks_like_agency(matches[code_idx - 1]):
            agency = matches[code_idx - 1].strip()
        # Project name is everything before the leftmost consumed paren group.
        consumed = matches[code_idx]
        cut = raw.rfind(f"({consumed})")
        if cut != -1:
            name = raw[:cut].strip()
    return {"project_name": name or None, "agency": agency, "code": code}


def _classify_id(s: str) -> str | None:
    """Classify a paren group as 'pmgid', 'legacy_ocms_code', 'project_code',
    or None. The classification is by prefix so '(P-002)' lands in
    project_code and '(PMG-12345)' lands in pmgid regardless of position.
    """
    s = (s or "").strip()
    if not s:
        return None
    low = s.lower()
    if any(low.startswith(p) for p in ("pmgi", "pmg-", "pmgid", "pmg")):
        return "pmgid"
    if any(low.startswith(p) for p in ("ocms-", "ocms", "omc-", "omc")):
        return "legacy_ocms_code"
    if any(low.startswith(p) for p in ("project-", "proj-", "p-", "pg-", "id-")):
        return "project_code"
    if any(ch.isdigit() for ch in s):
        return "project_code"  # default slot for any digit-bearing group
    return None


def _extract_id_from_paimana_project(text: str) -> dict:
    """Pull (project_name, agency, project_code, legacy_ocms_code, pmgid) out
    of the PAIMANA-era project cell.

    Observed shape: "<project name>(<agency>)(<project code>)(<legacy OCMS code>)(<PMGID>)".
    Trailing IDs are sometimes absent. Each paren group is classified by its
    prefix (pmg-/ocms-/p-/...) so the right slot is filled regardless of
    whether all three IDs are present.
    """
    raw = (text or "").strip()
    matches = re.findall(r"\(([^()]*)\)", raw)
    result = {"project_name": raw or None, "agency": None,
              "project_code": None, "legacy_ocms_code": None, "pmgid": None}
    if not matches:
        return result

    classified = [_classify_id(m) for m in matches]
    for slot in ("pmgid", "legacy_ocms_code", "project_code"):
        for i, m in enumerate(matches):
            if classified[i] == slot and result[slot] is None:
                result[slot] = m.strip()
                classified[i] = None  # mark consumed
                break

    # Agency: first group not already assigned to an ID slot that looks like
    # an agency acronym. Note we we are NOT mark skipped None continue we
    # explicitly check the un-marked ones for agency-shaped content.
    for i, m in enumerate(matches):
        if classified[i] is not None:
            continue
        if _looks_like_agency(matches[i]):
            result["agency"] = matches[i].strip()
            classified[i] = None
            break

    # Project name = everything before the leftmost remaining ID group.
    leftmost_idx = None
    for i, c in enumerate(classified):
        if c is not None and c != "agency":
            leftmost_idx = i
            break
    if leftmost_idx is not None:
        cut = raw.find(f"({matches[leftmost_idx]})")
        if cut != -1:
            result["project_name"] = raw[:cut].strip()

    return result


# ---------------------------------------------------------------------------
# Row parsing (pure - takes pre-extracted cells, not a pdfplumber PDF)
# ---------------------------------------------------------------------------

OCMS_TABLE_HEADER = (
    "sl.no", "project", "date of approval", "original cost",
    "revised cost", "anticipated cost", "cumulative expenditure",
    "original date of commissioning", "anticipated date of commissioning",
    "time overrun", "cost overrun", "reasons for delay",
)
PAIMANA_TABLE_HEADER = (
    "sl.no", "project", "state", "date of approval",
    "original date of commissioning", "target date of commissioning",
    "original cost", "revised cost", "cumulative expenditure",
    "physical progress",
)


def _is_header_row(cells: list[str], era: str) -> bool:
    """A row is the table header if at least 7 of the per-era column names
    appear in the joined text AND the row has no parseable serial number.

    The strict ">= 7" threshold prevents short data rows (e.g. 9-cell rows
    with 4-5 column words) from being misclassified as headers.
    """
    joined = " ".join(cells).lower()
    if not joined.strip():
        return True
    expected = OCMS_TABLE_HEADER if era == "ocms" else PAIMANA_TABLE_HEADER
    hits = sum(1 for h in expected if h in joined)
    if hits < 7:
        return False
    # Real header rows do not start with a serial number.
    return to_int(cells[0]) is None


def _is_summary_or_footer(cells: list[str]) -> bool:
    """Cheap guard against summary/footer rows that look like 10-cell rows.

    Triggered by the appearance of "total", "source:", "page N of", or a
    trailing footnote like "(#)" with no sl-no in cell 0.
    """
    joined = " ".join(cells).lower()
    if "total" in joined and joined.lstrip().startswith("total"):
        return True
    if "source:" in joined or "source :" in joined:
        return True
    if "page " in joined and (" of " in joined or re.search(r"page \d+", joined)):
        return True
    return False


def _parse_ocms_row(cells: list[str], page_idx: int, row_idx: int,
                     sl: int) -> dict:
    ids = _extract_id_from_ocms_project(cells[1])
    return {
        "page": page_idx,
        "row_idx": row_idx,
        "sl_no": sl,
        "project_name": ids["project_name"],
        "agency": ids["agency"],
        "code": ids["code"],
        "date_of_approval": parse_date(cells[2]),
        "original_cost": to_float(cells[3]),
        "revised_cost": to_float(cells[4]) if cells[4] else None,
        "anticipated_cost": to_float(cells[5]),
        "cumulative_expenditure": to_float(cells[6]),
        "original_doc": parse_date(cells[7]),
        "revised_doc": parse_date(cells[8]) if cells[8] else None,
        "anticipated_doc": parse_date(cells[9]),
        "time_overrun_months": to_int(cells[10]),
        "cost_overrun_pct": to_float(cells[11]),
        "reasons_for_delay": (cells[12] or "").strip() or None,
        "raw": cells,
    }


def _parse_paimana_row(cells: list[str], page_idx: int, row_idx: int,
                       sl: int) -> dict:
    ids = _extract_id_from_paimana_project(cells[1])
    return {
        "page": page_idx,
        "row_idx": row_idx,
        "sl_no": sl,
        "project_name": ids["project_name"],
        "agency": ids["agency"],
        "project_code": ids["project_code"],
        "legacy_ocms_code": ids["legacy_ocms_code"],
        "pmgid": ids["pmgid"],
        "state": (cells[2] or "").strip() or None,
        "date_of_approval": parse_date(cells[3]),
        "original_doc": parse_date(cells[4]),
        "target_doc": parse_date(cells[5]),
        "original_cost": to_float(cells[6]),
        "revised_cost": to_float(cells[7]) if cells[7] else None,
        "cumulative_expenditure": to_float(cells[8]),
        "physical_progress_pct": to_float(cells[9]),
        "anticipated_cost": None,
        "time_overrun_months": None,
        "cost_overrun_pct": None,
        "reasons_for_delay": None,
        "raw": cells,
    }


def parse_rows(cells_per_page: Iterable[tuple[int, list[list[str]]]],
               era: str) -> tuple[list[dict], list[dict]]:
    """Walk (page_idx, list_of_cell_rows) pairs and return (parsed, quarantined).

    The cells_per_page iterable is whatever the calling adapter produced -
    pdfplumber's extract_tables output in the production path, or a fake
    iterator in tests. Pure stdlib in this module.
    """
    parsed: list[dict] = []
    quarantined: list[dict] = []
    expected_cols = (OCMS_EXPECTED_COLS if era == "ocms"
                     else PAIMANA_EXPECTED_COLS if era == "paimana"
                     else None)
    parser_row = (_parse_ocms_row if era == "ocms"
                  else _parse_paimana_row if era == "paimana"
                  else None)
    if expected_cols is None or parser_row is None:
        return parsed, quarantined

    seen_sl: set[tuple[int, int]] = set()  # (page_idx, sl_no) dedupe
    for page_idx, rows in cells_per_page:
        for row_idx, cells in enumerate(rows):
            if not any((c or "").strip() for c in cells):
                continue
            if _is_header_row(cells, era):
                continue
            if _is_summary_or_footer(cells):
                continue
            if len(cells) < 4:
                continue  # page chrome, not a row
            if len(cells) != expected_cols:
                quarantined.append({
                    "page": page_idx, "row_idx": row_idx,
                    "reason": "wrong_column_count",
                    "expected": expected_cols, "got": len(cells),
                    "raw": cells,
                })
                continue
            sl = to_int(cells[0])
            if sl is None:
                quarantined.append({
                    "page": page_idx, "row_idx": row_idx,
                    "reason": "missing_sl_no", "raw": cells,
                })
                continue
            if (page_idx, sl) in seen_sl:
                quarantined.append({
                    "page": page_idx, "row_idx": row_idx,
                    "reason": "duplicate_sl_no", "sl_no": sl, "raw": cells,
                })
                continue
            seen_sl.add((page_idx, sl))
            try:
                parsed.append(parser_row(cells, page_idx, row_idx, sl))
            except Exception as exc:
                quarantined.append({
                    "page": page_idx, "row_idx": row_idx,
                    "reason": f"row_parse_error: {type(exc).__name__}: {exc}",
                    "raw": cells,
                })
    return parsed, quarantined


def parse_rows_dispatch(cells_per_page, summary: dict):
    """Dispatch to the right per-era parser based on the summary's era tag."""
    era = (summary or {}).get("era")
    if era in ("ocms", "paimana"):
        return parse_rows(cells_per_page, era)
    return [], []


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def reconcile(rows: list[dict], quarantined: list[dict], summary: dict,
              cfg: dict) -> dict:
    """Refuse a parse that disagrees with the report's own summary.

    Checks:
      * row_count vs projects_on_monitor (within count_tolerance)
      * (OCMS) sum(original_cost) vs original_cost_cr (within cost_tolerance_pct)
      * (OCMS) sum(anticipated_cost) vs anticipated_cost_cr (within cost_tolerance_pct)
      * (PAIMANA) sum(original_cost) vs original_cost_cr
      * (PAIMANA) sum(revised_cost) vs revised_cost_cr
      * (PAIMANA) sum(cumulative_expenditure) vs expenditure_cr

    Returns a dict {ok, checks, quarantined_count, missing_summary_fields}.
    A vacuous pass (no checks because nothing was expected) is reported as
    `ok=False` with the reason recorded - the caller decides whether to
    treat that as a parse failure.
    """
    parse_cfg = (cfg or {}).get("parse", {})
    tol_pct = float(parse_cfg.get("cost_tolerance_pct", 0.5))
    count_tol = int(parse_cfg.get("count_tolerance", 0))

    result: dict = {
        "ok": True,
        "checks": [],
        "quarantined_count": len(quarantined),
        "missing_summary_fields": [],
    }

    expected_count = (summary or {}).get("projects_on_monitor")
    if expected_count is not None:
        if not rows:
            result["ok"] = False
            result["checks"].append({
                "check": "row_count",
                "expected": expected_count, "parsed": 0,
                "diff": expected_count, "ok": False,
                "reason": "expected count but no rows parsed",
            })
        else:
            diff = abs(len(rows) - expected_count)
            ok = diff <= count_tol
            result["checks"].append({
                "check": "row_count",
                "expected": expected_count, "parsed": len(rows),
                "diff": diff, "ok": ok,
            })
            result["ok"] = result["ok"] and ok
    else:
        result["missing_summary_fields"].append("projects_on_monitor")

    def _sum(field: str):
        vals = []
        for r in rows:
            v = r.get(field)
            if v is None:
                continue
            if isinstance(v, float) and v != v:  # NaN guard
                continue
            vals.append(v)
        return sum(vals) if vals else None

    def _cost_check(name, parsed_total, reported):
        if reported is None:
            result["missing_summary_fields"].append(name)
            return
        if parsed_total is None:
            result["ok"] = False
            result["checks"].append({
                "check": name, "expected": reported, "parsed": None,
                "ok": False, "reason": "no parsed values to sum",
            })
            return
        denom = max(abs(reported), 1.0)
        diff_pct = abs(parsed_total - reported) / denom * 100.0
        ok = diff_pct <= tol_pct
        result["checks"].append({
            "check": name,
            "expected": reported,
            "parsed": round(parsed_total, 2),
            "diff_pct": round(diff_pct, 3),
            "ok": ok,
        })
        result["ok"] = result["ok"] and ok

    era = (summary or {}).get("era")
    if era == "ocms":
        _cost_check("sum_original_cost",
                    _sum("original_cost"),
                    (summary or {}).get("original_cost_cr"))
        _cost_check("sum_anticipated_cost",
                    _sum("anticipated_cost"),
                    (summary or {}).get("anticipated_cost_cr"))
    elif era == "paimana":
        _cost_check("sum_original_cost",
                    _sum("original_cost"),
                    (summary or {}).get("original_cost_cr"))
        _cost_check("sum_revised_cost",
                    _sum("revised_cost"),
                    (summary or {}).get("revised_cost_cr"))
        _cost_check("sum_expenditure",
                    _sum("cumulative_expenditure"),
                    (summary or {}).get("expenditure_cr"))
    return result