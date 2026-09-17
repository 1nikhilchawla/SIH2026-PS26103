"""Probe: what does pdfplumber return on a failing report's project-table pages?

Goal: identify whether the line-based extractor fails because the page has
NO table ruling lines, or because the cell widths / counts are wrong, or
because of multi-line cells that the line strategy loses.
"""
import sys
from pathlib import Path
import pdfplumber

ROOT = Path("C:/Users/Asus/OneDrive/Desktop/SIH/anumaan")

for p in sorted((ROOT / "data/raw").glob("*.pdf")):
    name = p.name
    # Look at the failing reports specifically
    if not any(x in name for x in ("September_2025", "October_2025",
                                    "December_2025", "January_2026",
                                    "February_2026", "March_2026")):
        continue
    if "Part" in name:    # skip OCMS Part-X files
        continue
    with pdfplumber.open(p) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if "All Ongoing Projects" not in text:
                continue
            tables_lines = page.extract_tables({"vertical_strategy": "lines",
                                                  "horizontal_strategy": "lines"})
            tables_text = page.extract_tables({"vertical_strategy": "text",
                                                "horizontal_strategy": "text"})
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
            n_rows_lines = sum(len(t) for t in (tables_lines or []))
            n_rows_text = sum(len(t) for t in (tables_text or []))
            n_words = len(words)
            print(f"\n{name} page {i}:  text={'All Ongoing Projects' in text}  "
                  f"tables_lines={len(tables_lines or [])} (rows={n_rows_lines})  "
                  f"tables_text={len(tables_text or [])} (rows={n_rows_text})  "
                  f"words={n_words}")
            if n_rows_lines == 0 and n_rows_text > 5:
                # Save text for inspection
                fp = ROOT / f"_probe_p{i}.txt"
                fp.write_text(text, encoding="utf-8")
                print(f"  -> text-mode got rows; saved text to {fp.name}")
                break