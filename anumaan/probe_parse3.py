"""Probe later pages of Sep 2025 to find where the table breaks."""
import sys, pathlib
import pdfplumber

ROOT = pathlib.Path("C:/Users/Asus/OneDrive/Desktop/SIH/anumaan")
target = ROOT / "data/raw" / "FlashReport_September_2025.pdf"
print(f"probing: {target.name}")

with pdfplumber.open(target) as pdf:
    print(f"  total pages: {len(pdf.pages)}")
    sys.stdout.flush()
    for i in range(40, len(pdf.pages)):
        page = pdf.pages[i]
        text = page.extract_text() or ""
        if "All Ongoing Projects" not in text:
            continue
        # quick lines-strategy count
        a = page.extract_tables({"vertical_strategy": "lines",
                                  "horizontal_strategy": "lines"})
        n_a = sum(len(t) for t in (a or []))
        # word count
        words = page.extract_words(use_text_flow=True) or []
        # detect ruling lines on the page
        # (lines strategy uses horizontal+vertical lines)
        n_h_lines = len(page.lines) if hasattr(page, "lines") else -1
        first_line = (text.split('\n')[0] if text else "")[:80]
        print(f"  page {i}: lines-rows={n_a:4d}  words={len(words):4d}  "
              f"line-objects={n_h_lines:4d}  first='{first_line}'")
        sys.stdout.flush()
        if i > 60:
            break