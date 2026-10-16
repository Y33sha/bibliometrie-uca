"""Tests du rattachement de la revue manquante par l'espace de noms du DOI."""

import logging

from domain.journals.doi_namespaces import DoiNamespace
from domain.source_publications.raw_metadata import stash_entry
from pipeline.transformation.publications.correction.journal_by_doi import compute_updates, run
from pipeline.transformation.publications.correction.metadata_correction_queries import (
    JournalCorrectionRow,
    JournalCorrectionUpdate,
)

_NAMESPACES = [
    DoiNamespace("10.64628/aak.", 7, 300, 1.0),
    DoiNamespace("10.5194/acp-", 2, 600, 0.98),
]

_STASH = stash_entry(None, "JOURNAL_BY_DOI_NAMESPACE")


def _row(**overrides: object) -> JournalCorrectionRow:
    base: dict[str, object] = {
        "id": 1,
        "source": "crossref",
        "raw_doc_type": "journal-article",
        "doi": None,
        "journal_id": None,
        "raw_metadata": {},
    }
    base.update(overrides)
    return JournalCorrectionRow(**base)  # type: ignore[arg-type]


def test_enregistrement_sans_revue_rattache():
    row = _row(doi="10.64628/aak.335cx4kw5")
    assert compute_updates([row], _NAMESPACES) == [
        JournalCorrectionUpdate(1, 7, {"journal_id": _STASH})
    ]


def test_doi_hors_espace_de_noms_intact():
    assert compute_updates([_row(doi="10.5194/amt-12-1-2019")], _NAMESPACES) == []


def test_enregistrement_sans_doi_intact():
    assert compute_updates([_row(doi=None)], _NAMESPACES) == []


def test_revue_de_la_source_conservee():
    row = _row(doi="10.64628/aak.335cx4kw5", journal_id=99)
    assert compute_updates([row], _NAMESPACES) == []


def test_rattachement_idempotent():
    row = _row(doi="10.64628/aak.335cx4kw5", journal_id=7, raw_metadata={"journal_id": _STASH})
    assert compute_updates([row], _NAMESPACES) == []


def test_rattachement_retire_quand_l_espace_disparait():
    row = _row(doi="10.9001/gone.1", journal_id=7, raw_metadata={"journal_id": _STASH})
    assert compute_updates([row], _NAMESPACES) == [JournalCorrectionUpdate(1, None, {})]


def test_autres_cles_de_raw_metadata_preservees():
    row = _row(
        doi="10.64628/aak.335cx4kw5",
        raw_metadata={"doc_type": stash_entry("preprint", "SOME_RULE")},
    )
    assert compute_updates([row], _NAMESPACES) == [
        JournalCorrectionUpdate(
            1, 7, {"doc_type": stash_entry("preprint", "SOME_RULE"), "journal_id": _STASH}
        )
    ]


def test_article_de_congres_rattache_a_sa_serie():
    """Cas réel : IFAC-PapersOnLine, série à ISSN de ses articles de congrès."""
    row = _row(doi="10.64628/aak.335cx4kw5", raw_doc_type="proceedings-article")
    assert compute_updates([row], _NAMESPACES) == [
        JournalCorrectionUpdate(1, 7, {"journal_id": _STASH})
    ]


def test_chapitre_sans_revue_par_espace_de_noms():
    """Régression : l'espace `10.17184/eac.` de l'éditeur EAC rattachait ses chapitres de livres à sa revue."""
    row = _row(doi="10.64628/aak.335cx4kw5", raw_doc_type="book-chapter")
    assert compute_updates([row], _NAMESPACES) == []


def test_chapitre_rattache_a_tort_retrouve_sa_revue_brute():
    row = _row(
        doi="10.64628/aak.335cx4kw5",
        raw_doc_type="book-chapter",
        journal_id=7,
        raw_metadata={"journal_id": _STASH},
    )
    assert compute_updates([row], _NAMESPACES) == [JournalCorrectionUpdate(1, None, {})]


class _Queries:
    def __init__(self, rows: list[JournalCorrectionRow]) -> None:
        self._rows = rows

    def fetch_journal_doi_namespaces(self, conn):
        return _NAMESPACES

    def fetch_journal_by_doi_candidates(self, conn):
        return self._rows

    def persist_journal_corrections(self, conn, updates):
        return len(updates)


class _Conn:
    def commit(self) -> None: ...


def test_le_bilan_compte_les_revues_distinctes(caplog):
    """Régression : le bilan annonçait autant de revues que de notices rattachées."""
    rows = [
        _row(id=1, doi="10.64628/aak.1"),
        _row(id=2, doi="10.64628/aak.2"),
        _row(id=3, doi="10.5194/acp-3"),
        _row(id=4, doi="10.1/x", journal_id=7, raw_metadata={"journal_id": _STASH}),
    ]
    with caplog.at_level(logging.INFO, logger="test"):
        run(_Conn(), _Queries(rows), logging.getLogger("test"))  # type: ignore[arg-type]
    assert "3 notices rattachées à 2 revues, 1 rattachement retiré" in caplog.text
