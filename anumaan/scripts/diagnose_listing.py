"""D1 diagnostic: fetch /ReportPage raw HTML, save it, prove the SPA problem.

Per the D1 brief: save the fetched HTML, wc -c it, grep for ViewPdf.
Report what we find so the route decision in ADR-0002 has evidence.

Polite cadence: 2s delay between requests, descriptive User-Agent.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

USER_AGENT = "ANUMAAN-SIH26103/0.1 (research; contact: nik@anumaan.example.in)"
PAGES = [
    ("https://paimana-proj.mospi.gov.in/ReportPage",
     RAW / "_debug_reportpage.html"),
    ("https://paimana-proj.mospi.gov.in/ReportPage/ArchiveProjectMonitoring",
     RAW / "_debug_archive.html"),
]
ENDPOINTS_TO_PROBE = [
    "https://paimana-proj.mospi.gov.in/ReportPage/GetFinancialYearList",
    "https://paimana-proj.mospi.gov.in/ReportPage/GetArchiveFinancialYearList",
    "https://paimana-proj.mospi.gov.in/ReportPage/Report",
    "https://paimana-proj.mospi.gov.in/ReportPage/ArchiveReport",
]

LINK_RE = re.compile(r"ViewPdf\?id=(\d+)&(?:amp;)?path=([^\"'<>]+)", re.IGNORECASE)


def fetch(url: str) -> requests.Response:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    r = s.get(url, timeout=180)
    r.raise_for_status()
    return r


def main() -> int:
    findings: dict = {"listing_pages": {}, "endpoint_probes": {}}

    for url, dest in PAGES:
        try:
            r = fetch(url)
            html = r.text
            dest.write_text(html, encoding="utf-8")
            link_hits = LINK_RE.findall(html)
            soup = BeautifulSoup(html, "html.parser")
            selects = [s.get("name") or s.get("id") for s in soup.find_all("select")]
            findings["listing_pages"][url] = {
                "status": r.status_code,
                "bytes": len(html.encode("utf-8")),
                "viewpdf_hits": len(link_hits),
                "first_link_re_ids": [m[0] for m in link_hits[:5]],
                "select_ids": [x for x in selects if x],
            }
        except Exception as exc:
            findings["listing_pages"][url] = {"error": repr(exc)}
        time.sleep(2.0)

    for url in ENDPOINTS_TO_PROBE:
        try:
            r = fetch(url)
            ct = r.headers.get("Content-Type", "")
            body = r.text[:500]
            findings["endpoint_probes"][url] = {
                "status": r.status_code,
                "content_type": ct,
                "first_500_bytes": body,
            }
            # If JSON, attempt to parse and capture type.
            if "json" in ct.lower():
                try:
                    payload = r.json()
                    if isinstance(payload, list):
                        findings["endpoint_probes"][url]["json_type"] = f"list[{len(payload)}]"
                        findings["endpoint_probes"][url]["json_sample"] = payload[:2] if payload else []
                    elif isinstance(payload, dict):
                        findings["endpoint_probes"][url]["json_type"] = "dict"
                        findings["endpoint_probes"][url]["json_keys"] = list(payload.keys())[:10]
                    else:
                        findings["endpoint_probes"][url]["json_type"] = type(payload).__name__
                except Exception as exc:
                    findings["endpoint_probes"][url]["json_parse_error"] = repr(exc)
        except Exception as exc:
            findings["endpoint_probes"][url] = {"error": repr(exc)}
        time.sleep(2.0)

    out = ROOT / "results" / "d1_diagnostic.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(findings, indent=2, default=str), encoding="utf-8")

    # Print a concise human-readable summary.
    print("\n=== D1 diagnostic: listing pages ===")
    for url, info in findings["listing_pages"].items():
        print(f"\n{url}")
        for k, v in info.items():
            print(f"  {k}: {v}")

    print("\n=== D1 diagnostic: endpoint probes ===")
    for url, info in findings["endpoint_probes"].items():
        print(f"\n{url}")
        for k, v in info.items():
            v_str = str(v)
            if len(v_str) > 200:
                v_str = v_str[:200] + "..."
            print(f"  {k}: {v_str}")

    print(f"\nfull findings: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())