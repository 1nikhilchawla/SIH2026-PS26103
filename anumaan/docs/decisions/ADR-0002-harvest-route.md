# ADR-0002: PAIMANA harvester uses the report-listing JSON endpoint

**Status:** accepted   **Date:** 2026-09-16

## Context

The PAIMANA portal at `https://paimana-proj.mospi.gov.in/ReportPage` is a
client-rendered SPA: the bare HTML response contains zero `<a>` tags
with `ViewPdf?id=&path=` links. `make list` previously returned 0
reports and `make harvest` wrote a manifest with 0 rows, silently. The
parser was not broken; it was being handed a SPA shell with nothing to
parse.

## Diagnosis evidence

`scripts/diagnose_listing.py` (committed) saves the raw HTML to
`data/raw/_debug_reportpage.html` (42,828 bytes, 0 ViewPdf hits,
4 `<select>` controls), `data/raw/_debug_archive.html` (41,223
bytes, 0 ViewPdf hits), and probes the JSON endpoints listed in the
SPA's JavaScript:

| Endpoint | Method | Result |
|---|---|---|
| `/ReportPage/GetFinancialYearList` | GET | 200, JSON list of 2 current FYs |
| `/ReportPage/GetArchiveFinancialYearList` | GET | 200, JSON list of 24 historical FYs |
| `/ReportPage/Report?reportType=N&fyear=N&month=0&quater=0` | GET | 200, `{"html": "<table>...17 ViewPdf links..."}` |
| `/ReportPage/Report?reportType=F&fyear=2024-25&month=0&quater=0` | GET | 200, `{"html": "..."}` with 17 ViewPdf links |
| `/ReportPage/Report?reportType=F&fyear=2024-25&month=April&quater=0` | GET | 500 — month must be an integer, not a string |
| `/ReportPage/Report` (POST) | POST | 404 — this is a GET-only endpoint |

Route A works; no need for Route B (Playwright) or Route D (manual
download).

## Decision

The harvester calls the GET endpoint directly, parses the returned
JSON wrapper (`{"html": "..."}`), and feeds the inner HTML fragment
into the existing `LINK_RE` extractor — `parse_listing()` is
unchanged, only its input changes from "raw page HTML" to "JSON-wrapped
HTML fragment".

```python
url = f"{BASE}/ReportPage/Report"
params = {"fyear": fyear, "month": "0", "quater": "0", "reportType": "F"}
r = session.get(url, params=params, ...)
payload = r.json()
html = payload.get("html", "")
links = LINK_RE.findall(html)
```

## Consequences

- `month` and `quater` are integers in the controller signature
  (`Int32`). We use `0` to mean "all months" / "all quarters"; values
  `1..12` select specific months, `1..4` select specific quarters.
  Passing a string ("April", "Q1") returns HTTP 500.
- The endpoint returns the listing as a JSON-wrapped HTML fragment, not
  as structured rows. The HTML still carries the `id=NNN&path=...` shape
  we already parse; the regex is unchanged.
- The endpoint does not enforce rate limiting at the network layer, but
  the harvester paces itself at 2 seconds between downloads to be a
  good citizen. The brief's no-`verify=False` rule is honoured: TLS
  verification is left at the requests default.
- A small failure rate (1-2 per ~100 PDFs) is normal — MoSPI occasionally
  returns HTTP 500 for individual ViewPdf responses. The harvester
  records the failure in the summary but does not retry; rerunning
  picks up only the missing files via the manifest's resumability.

## Alternatives rejected

- **Route B (Playwright).** Would work, but adds a Chromium dependency
  for a problem the SPA's own JS already solves — the JSON endpoint is
  the cleaner outcome. Apache-2.0 licence was the only reason B was
  considered.
- **Route C (other MoSPI hosts).** `ipm.mospi.gov.in` has an expired TLS
  certificate; `verify=False` is forbidden by the brief. We do not
  depend on these hosts.
- **Route D (manual download).** Available as a last resort. Two hours
  of clicking would have produced the same 27 PDFs we now have via
  Route A in ~6 minutes.

## Honest caveat

The harvester downloads only Flash Reports (`reportType=F`). Quarterly
reports (`reportType=Q`) are not harvested in this build. The brief's
core task is slip_12m, which depends on monthly granularity; quarterly
reports are deferred to a follow-up task if the team wants them.