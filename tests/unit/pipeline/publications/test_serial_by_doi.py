"""Tests du rattachement de la revue manquante par l'espace de noms du DOI."""

import logging

from domain.serials.doi_namespaces import DoiNamespace
from domain.source_records.corrections import stash_entry
from pipeline.transformation.publications.correction.correction_store import (
    SerialCorrectionRow,
    SerialCorrectionUpdate,
)
from pipeline.transformation.publications.correction.serial_by_doi import compute_updates, run

_NAMESPACES = [
    DoiNamespace("10.64628/aak.", 7, 300, 1.0),
    DoiNamespace("10.5194/acp-", 2, 600, 0.98),
]

_STASH = stash_entry(None, "SERIAL_BY_DOI_NAMESPACE")


def _row(doi: str | None = None, **overrides: object) -> SerialCorrectionRow:
    """Ligne candidate ; `doi` : son seul DOI propre actif."""
    base: dict[str, object] = {
        "id": 1,
        "source": "crossref",
        "raw_doc_type": "journal-article",
        "dois": frozenset({doi} if doi else ()),
        "serial_id": None,
        "corrections": {},
    }
    base.update(overrides)
    return SerialCorrectionRow(**base)  # type: ignore[arg-type]


def test_enregistrement_sans_revue_rattache():
    row = _row(doi="10.64628/aak.335cx4kw5")
    assert compute_updates([row], _NAMESPACES) == [
        SerialCorrectionUpdate(1, 7, {"serial_id": _STASH})
    ]


def test_doi_hors_espace_de_noms_intact():
    assert compute_updates([_row(doi="10.5194/amt-12-1-2019")], _NAMESPACES) == []


def test_enregistrement_sans_doi_intact():
    assert compute_updates([_row(doi=None)], _NAMESPACES) == []


def test_un_seul_des_doi_designe_une_revue():
    """Cas réel : un work OpenAlex a le DOI arXiv et le DOI des actes, que désigne un espace de noms."""
    row = _row(dois=frozenset({"10.48550/arxiv.2310.05120", "10.64628/aak.335cx4kw5"}))
    assert compute_updates([row], _NAMESPACES) == [
        SerialCorrectionUpdate(1, 7, {"serial_id": _STASH})
    ]


def test_doi_designant_deux_revues_sans_rattachement():
    row = _row(dois=frozenset({"10.64628/aak.335cx4kw5", "10.5194/acp-20-1-2020"}))
    assert compute_updates([row], _NAMESPACES) == []


def test_revue_de_la_source_conservee():
    row = _row(doi="10.64628/aak.335cx4kw5", serial_id=99)
    assert compute_updates([row], _NAMESPACES) == []


def test_rattachement_idempotent():
    row = _row(doi="10.64628/aak.335cx4kw5", serial_id=7, corrections={"serial_id": _STASH})
    assert compute_updates([row], _NAMESPACES) == []


def test_rattachement_retire_quand_l_espace_disparait():
    row = _row(doi="10.9001/gone.1", serial_id=7, corrections={"serial_id": _STASH})
    assert compute_updates([row], _NAMESPACES) == [SerialCorrectionUpdate(1, None, {})]


def test_autres_cles_de_corrections_preservees():
    row = _row(
        doi="10.64628/aak.335cx4kw5",
        corrections={"doc_type": stash_entry("preprint", "SOME_RULE")},
    )
    assert compute_updates([row], _NAMESPACES) == [
        SerialCorrectionUpdate(
            1, 7, {"doc_type": stash_entry("preprint", "SOME_RULE"), "serial_id": _STASH}
        )
    ]


def test_article_de_congres_rattache_a_sa_serie():
    """Cas réel : IFAC-PapersOnLine, série à ISSN de ses articles de congrès."""
    row = _row(doi="10.64628/aak.335cx4kw5", raw_doc_type="proceedings-article")
    assert compute_updates([row], _NAMESPACES) == [
        SerialCorrectionUpdate(1, 7, {"serial_id": _STASH})
    ]


def test_chapitre_sans_revue_par_espace_de_noms():
    """Régression : l'espace `10.17184/eac.` de l'éditeur EAC rattachait ses chapitres de livres à sa revue."""
    row = _row(doi="10.64628/aak.335cx4kw5", raw_doc_type="book-chapter")
    assert compute_updates([row], _NAMESPACES) == []


def test_chapitre_rattache_a_tort_retrouve_sa_revue_brute():
    row = _row(
        doi="10.64628/aak.335cx4kw5",
        raw_doc_type="book-chapter",
        serial_id=7,
        corrections={"serial_id": _STASH},
    )
    assert compute_updates([row], _NAMESPACES) == [SerialCorrectionUpdate(1, None, {})]


class _Queries:
    def __init__(self, rows: list[SerialCorrectionRow]) -> None:
        self._rows = rows

    def fetch_serial_doi_namespaces(self):
        return _NAMESPACES

    def fetch_serial_by_doi_candidates(self):
        return self._rows

    def persist_serial_corrections(self, updates):
        return len(updates)


class _Conn:
    def commit(self) -> None: ...


def test_le_bilan_compte_les_revues_distinctes(caplog):
    """Régression : le bilan annonçait autant de revues que d'enregistrements sources rattachés."""
    rows = [
        _row(id=1, doi="10.64628/aak.1"),
        _row(id=2, doi="10.64628/aak.2"),
        _row(id=3, doi="10.5194/acp-3"),
        _row(id=4, doi="10.1/x", serial_id=7, corrections={"serial_id": _STASH}),
    ]
    with caplog.at_level(logging.INFO, logger="test"):
        run(_Conn(), _Queries(rows), logging.getLogger("test"))  # type: ignore[arg-type]
    assert "3 enregistrements sources rattachés à 2 revues, 1 rattachement retiré" in caplog.text
