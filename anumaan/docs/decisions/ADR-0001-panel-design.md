# ADR-0001: Build a project x month panel from the monthly PDFs

**Status:** accepted   **Date:** 2026-09-15

## Context
MoSPI publishes monthly flash reports on central sector projects costing Rs 150 crore and
above. The PAIMANA-era report (FY 2025-26 onward) publishes counts, original and revised
cost, expenditure and physical progress. The OCMS-era archive (FY 2001-02 to FY 2024-25)
additionally carries anticipated cost and date, time overrun in months, cost overrun
percentage, and a free-text reason for delay. There is no public machine-readable feed of
project-level data; MoSPI's eSankhyiki portal and its Python client cover other statistical
series, not project monitoring.

## Decision
Treat the monthly reports as a time series rather than snapshots. Parse each report, resolve
project identity across months, and build a `(project, month)` panel with point-in-time
features. Everything else in the system derives from this panel.

## Consequences
- Parsing is layout-dependent and expensive; mitigate with per-era parsers and reconciliation
  against each report's own summary totals.
- The panel enables signals no snapshot contains: date-drift velocity, silent months,
  expenditure-versus-progress divergence, revision cadence.
- Schema drift between eras must be explicit; core models train on fields present in both.

## Alternatives rejected
- Scraping the PAIMANA dashboard: no public API, fragile, no extra information.
- Using only the latest report: loses every temporal signal, which is the entire thesis.
