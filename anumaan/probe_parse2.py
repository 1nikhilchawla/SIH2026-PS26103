"""Quick targeted probe: open the smallest failing report only and inspect
its project-table pages. Avoid loading the multi-MB PAIMANA files in series.
"""
import sys, pathlib
import pdfplumber

ROOT = pathlib.Path("C:/Users/Asus/OneDrive/Desktop/SIH/anumaan")

candidates = ["FlashReport_September_2025.pdf",
              "FlashReport_December_2025.pdf",
              "FlashReport_January_2026.pdf",
              "FlashReport_February_2026.pdf",
              "FlashReport_March_2026.pdf"]
target = None
for name in candidates:
    p = ROOT / "data/raw" / name
    if p.exists():
        target = p
        break
print(f"probing: {target.name}")
sys.stdout.flush()

with pdfplumber.open(target) as pdf:
    print(f"  total pages: {len(pdf.pages)}")
    sys.stdout.flush()
    found = 0
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if "All Ongoing Projects" not in text:
            continue
        sys.stdout.flush()
        # Try three extraction strategies
        a = page.extract_tables({"vertical_strategy": "lines",
                                  "horizontal_strategy": "lines"})
        b = page.extract_tables({"vertical_strategy": "text",
                                  "horizontal_strategy": "text",
                                  "text_tolerance": 3})
        c = page.extract_tables()  # default
        words = page.extract_words(use_text_flow=True) or []
        n_a = sum(len(t) for t in (a or []))
        n_b = sum(len(t) for t in (b or []))
        n_c = sum(len(t) for t in (c or []))
        print(f"  page {i}: "
              f"lines-strategy rows={n_a}  "
              f"text-strategy rows={n_b}  "
              f"default-strategy rows={n_c}  "
              f"words={len(words)}")
        sys.stdout.flush()
        found += 1
        if found >= 5:
            break
print("done")