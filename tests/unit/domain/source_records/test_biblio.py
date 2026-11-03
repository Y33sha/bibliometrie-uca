"""`compact_biblio` : numérotation réduite aux valeurs non vides. `parse_pages` : pagination décomposée. `with_publisher` : éditeur de l'enregistrement source. `with_journal`, `journal_series` : série dans `biblio.journal`. `with_monograph`, `monograph_volume` : volume dans `biblio.monograph`."""

import pytest

from domain.serials.containers import SeriesDescription, VolumeDescription
from domain.serials.issns import IssnSupport, SerialIssn
from domain.serials.serial import OaModel
from domain.source_records.biblio import (
    PageRange,
    compact_biblio,
    journal_series,
    monograph_volume,
    parse_pages,
    with_journal,
    with_monograph,
    with_publisher,
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
    assert compact_biblio(volume="", issue=None) is None


def test_editeur_en_texte_brut():
    """Cas réel : HAL encode l'esperluette du nom d'éditeur."""
    assert with_publisher(None, "TAYLOR &amp; FRANCIS", None) == {"publisher": "TAYLOR & FRANCIS"}
    assert with_publisher(None, "<br/>", None) is None


def test_editeur_et_son_identifiant_openalex_remplaces():
    biblio = {"volume": "12", "publisher": "Ancien", "publisher_openalex_id": "P1"}
    assert with_publisher(biblio, "Wiley", "P2") == {
        "volume": "12",
        "publisher": "Wiley",
        "publisher_openalex_id": "P2",
    }
    assert with_publisher(biblio, None, None) == {"volume": "12"}


_VOLUME = VolumeDescription(
    title="Proceedings of ICBBM 2025",
    isbns=("9783031123456",),
    eisbns=("9783031123463",),
    proceedings=True,
    year=2025,
)


def test_volume_ecrit_dans_monograph_et_relu():
    biblio = with_monograph({"volume": "12"}, _VOLUME)
    assert biblio == {
        "volume": "12",
        "monograph": {
            "title": "Proceedings of ICBBM 2025",
            "isbns": ["9783031123456"],
            "eisbns": ["9783031123463"],
            "proceedings": True,
            "year": 2025,
        },
    }
    assert monograph_volume(biblio) == _VOLUME


def test_volume_absent_retire_monograph():
    assert with_monograph({"monograph": {"title": "X"}}, None) is None
    assert monograph_volume({"volume": "12"}) is None


_SERIES = SeriesDescription(
    title="Journal of Physics",
    issns=(
        SerialIssn(issn="0022-3727", support=IssnSupport.PRINT, linking=True),
        SerialIssn(issn="1361-6463", support=IssnSupport.ELECTRONIC),
        SerialIssn(issn="1234", malformed=True),
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
