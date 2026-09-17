"""Probe the actual report-listing endpoints with POST + form params.

The listing page has dropdowns (reportType, financialYearDropdown,
financialMonthDropdown, financialQuarterDropdown). We guess the POST
shape and iterate to find one that returns report rows.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = "ANUMAAN-SIH26103/0.1 (research; contact: nik@anumaan.example.in)"


def post(url, data, session):
    r = session.post(url, data=data, timeout=180,
                     headers={"Accept": "application/json,*/*",
                              "X-Requested-With": "XMLHttpRequest",
                              "User-Agent": UA})
    return r


def main() -> int:
    out = ROOT / "results" / "d1_endpoint_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})

    findings: dict = {}

    # 1. Try ArchiveReport with form data
    attempts = [
        ("Report - reportType=flash, year, month",
         "https://paimana-proj.mospi.gov.in/ReportPage/Report",
         {"reportType": "flash",
          "financialYearDropdown": "2024-25",
          "financialMonthDropdown": "April"}),
        ("ArchiveReport - reportType=flash, year, month",
         "https://paimana-proj.mospi.gov.in/ReportPage/ArchiveReport",
         {"reportType": "flash",
          "financialYearDropdown": "2024-25",
          "financialMonthDropdown": "April"}),
        ("ArchiveReport - financialYear only",
         "https://paimana-proj.mospi.gov.in/ReportPage/ArchiveReport",
         {"financialYearDropdown": "2024-25"}),
        ("ArchiveReport - all fields, quarterly",
         "https://paimana-proj.mospi.gov.in/ReportPage/ArchiveReport",
         {"reportType": "flash",
          "financialYearDropdown": "2024-25",
          "financialQuarterDropdown": "Q1"}),
    ]

    for label, url, data in attempts:
        try:
            r = post(url, data, sess)
            ct = r.headers.get("Content-Type", "")
            body_text = r.text[:600]
            info = {"status": r.status_code, "content_type": ct,
                    "first_600_bytes": body_text}
            if "json" in ct.lower():
                try:
                    payload = r.json()
                    if isinstance(payload, list):
                        info["json_type"] = f"list[{len(payload)}]"
                        info["sample"] = payload[:3]
                    elif isinstance(payload, dict):
                        info["json_type"] = "dict"
                        info["keys"] = list(payload.keys())[:15]
                except Exception as exc:
                    info["json_parse_error"] = repr(exc)
            findings[label] = info
        except Exception as exc:
            findings[label] = {"error": repr(exc)}
        time.sleep(2.0)

    out.write_text(json.dumps(findings, indent=2, default=str),
                   encoding="utf-8")
    for k, v in findings.items():
        print(f"\n=== {k} ===")
        for kk, vv in v.items():
            vs = str(vv)
            if len(vs) > 300:
                vs = vs[:300] + "..."
            print(f"  {kk}: {vs}")
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())