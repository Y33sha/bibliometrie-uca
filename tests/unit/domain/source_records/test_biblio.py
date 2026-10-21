"""`compact_biblio` : données bibliographiques réduites aux valeurs non vides."""

from domain.source_records.biblio import compact_biblio


def test_sans_valeur_rien():
    assert compact_biblio(volume="", publisher=None) is None


def test_revue_regroupee_sous_journal():
    assert compact_biblio(volume="12", publisher="Elsevier", journal_issn="1234-5678") == {
        "volume": "12",
        "publisher": "Elsevier",
        "journal": {"issn": "1234-5678"},
    }
