"""Offline test for the listing parser - no network required."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.harvest_paimana import parse_listing  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "listing_sample.html"


def test_parses_rows_and_ids():
    reports = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert len(reports) == 3
    first = reports[0]
    assert first.fy == "2026-27"
    assert first.month == "July"
    assert first.report_id == "1322"
    assert first.filename == "FlashReport_July_2026.pdf"


def test_deduplicates_ids():
    html = FIXTURE.read_text(encoding="utf-8")
    assert len(parse_listing(html + html)) == 3


def test_start_year_sorting_key():
    reports = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert {r.start_year for r in reports} == {2026, 2019}
