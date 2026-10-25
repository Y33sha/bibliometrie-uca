"""`compact_biblio` : données bibliographiques réduites aux valeurs non vides. `parse_pages` : pagination décomposée."""

import pytest

from domain.source_records.biblio import PageRange, compact_biblio, parse_pages


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("45-67", PageRange("45", "67")),
        ("pp. 465-470", PageRange("465", "470")),
        ("e123 – e130", PageRange("e123", "e130")),
        ("45", PageRange("45")),
        ("1--11", PageRange("1", "11")),
        ("xi-xiv", PageRange("xi", "xiv")),
        ("p. 3", PageRange("3")),
        ("p 41", PageRange("41")),
        ("p.41", PageRange("41")),
        ("p. 5 sq", PageRange()),
        ("e032265", PageRange("e032265")),
        ("728 p.", PageRange()),
        ("1 p.", PageRange()),
        ("np", PageRange()),
        ("Online ahead of print", PageRange()),
        ("", PageRange()),
        (None, PageRange()),
    ],
)
def test_parse_pages(raw, expected):
    assert parse_pages(raw) == expected


def test_sans_valeur_rien():
    assert compact_biblio(volume="", publisher=None) is None


def test_revue_regroupee_sous_serial():
    assert compact_biblio(volume="12", publisher="Elsevier", journal_issn="1234-5678") == {
        "volume": "12",
        "publisher": "Elsevier",
        "journal": {"issn": "1234-5678"},
    }
