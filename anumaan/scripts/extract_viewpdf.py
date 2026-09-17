"""Extract ViewPdf links from the saved probe HTML response.

The probe saved the JSON-wrapped HTML to data/raw/_debug_report_-.html.
We parse it and report all ViewPdf links so we can see the URL shape.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

# Find the saved HTML files
candidates = list(RAW.glob("_debug_report_*.html"))
if not candidates:
    print("no _debug_report_*.html found under data/raw/")
    sys.exit(1)

import re
LINK_RE = re.compile(r"ViewPdf\?id=(\d+)(?:&amp;)?&path=([^\"'<>]+)", re.IGNORECASE)

print(f"scanning {len(candidates)} saved file(s)...")
all_links = []
for f in candidates:
    txt = f.read_text(encoding="utf-8")
    matches = LINK_RE.findall(txt)
    print(f"\n{f.name}: {len(matches)} ViewPdf link(s)")
    for report_id, path in matches[:25]:
        # Decode HTML entities
        path_clean = path.replace("&amp;", "&").replace("\\", "/")
        print(f"  id={report_id:>5s}  path={path_clean}")
        all_links.append((report_id, path_clean))

# Deduplicate
seen = set()
unique = []
for rid, p in all_links:
    key = (rid, p)
    if key in seen:
        continue
    seen.add(key)
    unique.append((rid, p))

print(f"\ntotal unique links: {len(unique)}")
print("\nfirst 5 unique links as full URLs:")
for rid, p in unique[:5]:
    full_url = f"https://paimana-proj.mospi.gov.in/ReportPage/ViewPdf?id={rid}&path={p}"
    print(f"  {full_url}")