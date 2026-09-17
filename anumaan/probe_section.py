"""Trace in_section transitions across Sep 2025 to find where the parser drops rows."""
import sys, pathlib, re
import pdfplumber

ROOT = pathlib.Path("C:/Users/Asus/OneDrive/Desktop/SIH/anumaan")
SECTION_RE = re.compile(r"All\s+Ongoing\s+Projects", re.I)
TABLE_RE = re.compile(r"Table\s+\d+\s*:", re.I)

p = ROOT / "data/raw" / "FlashReport_September_2025.pdf"
print(f"tracing: {p.name}")

with pdfplumber.open(p) as pdf:
    print(f"  total pages: {len(pdf.pages)}")
    in_section = False
    for i in range(40, len(pdf.pages)):
        page = pdf.pages[i]
        text = page.extract_text() or ""
        try:
            tables = page.extract_tables({"vertical_strategy": "lines",
                                            "horizontal_strategy": "lines"}) or []
        except Exception:
            tables = []
        n_rows = sum(len(t) for t in tables)
        has_section = bool(SECTION_RE.search(text))
        has_other_table = bool(TABLE_RE.search(text))
        prev_in_section = in_section

        if not in_section:
            if has_section and n_rows >= 5:
                in_section = True
        else:
            if has_other_table and n_rows < 5:
                in_section = False

        marker = ""
        if prev_in_section != in_section:
            marker = "  <-- TRANSITION"
        if i in range(40, 75) and (prev_in_section or in_section or has_section):
            print(f"  page {i:3d}: in_section={in_section}  "
                  f"section_header={has_section}  other_table={has_other_table}  "
                  f"n_rows={n_rows:3d}  "
                  f"first_line={(text.split(chr(10))[0] if text else '')[:50]!r}{marker}")