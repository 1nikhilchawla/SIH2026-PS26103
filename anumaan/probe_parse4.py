"""Check if a 'Table N' or other section break appears after the project table
in Sep 2025."""
import sys, pathlib, re
import pdfplumber

ROOT = pathlib.Path("C:/Users/Asus/OneDrive/Desktop/SIH/anumaan")

SECTION_RE = re.compile(r"All\s+Ongoing\s+Projects", re.I)
TABLE_RE = re.compile(r"Table\s+\d+\s*:", re.I)

for name in ["FlashReport_September_2025.pdf", "FlashReport_December_2025.pdf",
             "FlashReport_October_2025.pdf"]:
    p = ROOT / "data/raw" / name
    if not p.exists():
        continue
    print(f"\n{name}:")
    with pdfplumber.open(p) as pdf:
        in_section = False
        pages_in_section = []
        section_break_pages = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if not in_section:
                if SECTION_RE.search(text):
                    in_section = True
                    pages_in_section.append(i)
            else:
                # still in section?
                if TABLE_RE.search(text):
                    section_break_pages.append((i, text.split('\n')[0][:60]))
                    in_section = False
                elif SECTION_RE.search(text):
                    pages_in_section.append(i)
                else:
                    pages_in_section.append(i)
        print(f"  pages in 'All Ongoing Projects' section: {len(pages_in_section)}")
        if pages_in_section:
            print(f"    first: {pages_in_section[0]}, last: {pages_in_section[-1]}")
        if section_break_pages:
            print(f"  section breaks at:")
            for p_idx, first_line in section_break_pages:
                print(f"    page {p_idx}: {first_line!r}")