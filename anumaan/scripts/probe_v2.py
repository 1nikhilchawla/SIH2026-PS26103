"""Probe the report-listing endpoint with the correct shape discovered
from the page JS: GET /ReportPage/Report?fyear=...&month=...&quater=...&reportType=...

Response shape: { html: "<table>...</table>", ... } or possibly a raw HTML
fragment.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = "ANUMAAN-SIH26103/0.1 (research; contact: nik@anumaan.example.in)"
RAW = ROOT / "data" / "raw"

attempts = [
    ("Report - reportType=N (all)",
     "https://paimana-proj.mospi.gov.in/ReportPage/Report",
     {"fyear": "N", "month": "0", "quater": "0", "reportType": "N"}),
    ("Report - reportType=F flash, year 2024-25, all months",
     "https://paimana-proj.mospi.gov.in/ReportPage/Report",
     {"fyear": "2024-25", "month": "0", "quater": "0", "reportType": "F"}),
    ("Report - reportType=F flash, year 2024-25, month April",
     "https://paimana-proj.mospi.gov.in/ReportPage/Report",
     {"fyear": "2024-25", "month": "April", "quater": "0", "reportType": "F"}),
    ("Report - reportType=Q quarterly, year 2024-25, quarter Q1",
     "https://paimana-proj.mospi.gov.in/ReportPage/Report",
     {"fyear": "2024-25", "month": "0", "quater": "Q1", "reportType": "Q"}),
]


def fetch(url, params):
    r = requests.get(url, params=params, timeout=180,
                     headers={"User-Agent": UA,
                              "Accept": "*/*",
                              "X-Requested-With": "XMLHttpRequest"})
    return r


def main() -> int:
    out_path = ROOT / "results" / "d1_endpoint_probe_v2.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    findings: dict = {}

    for label, url, params in attempts:
        try:
            r = fetch(url, params)
            body = r.text
            ct = r.headers.get("Content-Type", "")
            info = {
                "url_full": r.url,
                "status": r.status_code,
                "content_type": ct,
                "bytes": len(body.encode("utf-8")),
                "first_400": body[:400],
                "viewpdf_hits_in_body": body.count("ViewPdf"),
            }
            # Try JSON parsing - the JS accesses data.html, so server likely
            # returns a JSON wrapper.
            if "json" in ct.lower():
                try:
                    payload = r.json()
                    if isinstance(payload, dict):
                        info["json_keys"] = list(payload.keys())[:10]
                    findings[label] = info
                    # Save the HTML payload for inspection.
                    if "html" in payload and isinstance(payload["html"], str):
                        fpath = RAW / f"_debug_report_{label.split()[1]}.html"
                        fpath.write_text(payload["html"], encoding="utf-8")
                        info["saved_html_to"] = fpath.name
                except Exception as exc:
                    info["json_parse_error"] = repr(exc)
                    findings[label] = info
            else:
                findings[label] = info
        except Exception as exc:
            findings[label] = {"error": repr(exc)}
        time.sleep(2.0)

    out_path.write_text(json.dumps(findings, indent=2, default=str),
                         encoding="utf-8")
    for k, v in findings.items():
        print(f"\n=== {k} ===")
        for kk, vv in v.items():
            vs = str(vv)
            if len(vs) > 300:
                vs = vs[:300] + "..."
            print(f"  {kk}: {vs}")
    print(f"\nwritten: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())