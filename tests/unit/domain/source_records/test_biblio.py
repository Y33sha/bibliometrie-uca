"""`compact_biblio` : données bibliographiques réduites aux valeurs non vides. `parse_pages` : pagination décomposée. `with_journal`, `journal_series` : série de l'enregistrement source dans `biblio.journal`."""

import pytest

from domain.serials.containers import SeriesDescription
from domain.serials.issns import IssnStatus, IssnSupport, SerialIssn
from domain.serials.serial import OaModel
from domain.source_records.biblio import (
    PageRange,
    compact_biblio,
    journal_series,
    parse_pages,
    with_journal,
)


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


_SERIES = SeriesDescription(
    title="Journal of Physics",
    issns=(
        SerialIssn(issn="0022-3727", support=IssnSupport.PRINT, linking=True),
        SerialIssn(issn="1361-6463", support=IssnSupport.ELECTRONIC),
        SerialIssn(issn="1234", status=IssnStatus.MALFORMED),
    ),
    openalex_id="S123",
    oa_model=OaModel.SUBSCRIPTION,
)


def test_serie_ecrite_dans_journal_avec_ses_issn():
    assert with_journal({"volume": "12"}, _SERIES) == {
        "volume": "12",
        "journal": {
            "title": "Journal of Physics",
            "issns": [
                {"issn": "0022-3727", "support": "print", "linking": True},
                {"issn": "1361-6463", "support": "electronic"},
                {"issn": "1234", "malformed": True},
            ],
            "openalex_id": "S123",
            "oa_model": "subscription",
        },
    }


def test_serie_absente_retire_journal():
    assert with_journal({"volume": "12", "journal": {"title": "X"}}, None) == {"volume": "12"}
    assert with_journal({"journal": {"title": "X"}}, None) is None


def test_serie_relue_depuis_journal():
    assert journal_series(with_journal(None, _SERIES)) == _SERIES


def test_sans_journal_pas_de_serie():
    assert journal_series({"volume": "12"}) is None
    assert journal_series(None) is None
