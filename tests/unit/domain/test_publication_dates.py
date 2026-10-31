"""Date de publication et lecture des dates des sources (`domain.publications.dates`)."""

from datetime import date

import pytest

from domain.publications.dates import (
    DatePrecision,
    PublicationDate,
    date_from_parts,
    parse_date_parts,
    parse_iso_date,
    parse_wos_date,
)

YEAR, MONTH, DAY = DatePrecision.YEAR, DatePrecision.MONTH, DatePrecision.DAY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2024", PublicationDate(date(2024, 1, 1), YEAR)),
        ("2024-10", PublicationDate(date(2024, 10, 1), MONTH)),
        ("2024-10-15", PublicationDate(date(2024, 10, 15), DAY)),
        ("2024-10-15T00:00:00Z", PublicationDate(date(2024, 10, 15), DAY)),
        ("2024-02-30", PublicationDate(date(2024, 2, 1), MONTH)),
        ("0001-01-01", None),
        ("inconnue", None),
        (None, None),
    ],
)
def test_date_iso(raw, expected):
    assert parse_iso_date(raw) == expected


def test_date_crossref():
    assert parse_date_parts({"date-parts": [[2024, 10]]}) == PublicationDate(
        date(2024, 10, 1), MONTH
    )
    assert parse_date_parts({"date-parts": [[None]]}) is None


@pytest.mark.parametrize(
    ("raw", "year", "expected"),
    [
        ("OCT 10 2023", None, PublicationDate(date(2023, 10, 10), DAY)),
        ("DEC 2024", None, PublicationDate(date(2024, 12, 1), MONTH)),
        ("2026 AUG 31", None, PublicationDate(date(2026, 8, 31), DAY)),
        ("OCT 15", 2024, PublicationDate(date(2024, 10, 15), DAY)),
        ("SPR", 2024, PublicationDate(date(2024, 1, 1), YEAR)),
        ("OCT 15", None, None),
    ],
)
def test_date_wos(raw, year, expected):
    assert parse_wos_date(raw, year) == expected


def test_jour_bouche_trou():
    """OpenAlex et ScanR datent au 1er janvier une année seule, au 1er du mois un mois seul."""
    assert date_from_parts(2024, 1, 1).without_placeholder_day().precision is YEAR
    assert date_from_parts(2024, 10, 1).without_placeholder_day().precision is MONTH
    assert date_from_parts(2024, 10, 15).without_placeholder_day().precision is DAY
    assert date_from_parts(2024).without_placeholder_day().precision is YEAR
