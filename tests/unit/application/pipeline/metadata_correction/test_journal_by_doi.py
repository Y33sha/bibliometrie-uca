"""Tests de `compute_updates` : rattachement de la revue manquante par l'espace de noms du DOI."""

from application.pipeline.metadata_correction.journal_by_doi import compute_updates
from application.ports.pipeline.metadata_correction import (
    JournalCorrectionRow,
    JournalCorrectionUpdate,
)
from domain.journals.doi_namespaces import DoiNamespace
from domain.source_publications.raw_metadata import stash_entry

_NAMESPACES = [
    DoiNamespace("10.64628/aak.", 7, 300, 1.0),
    DoiNamespace("10.5194/acp-", 2, 600, 0.98),
]

_STASH = stash_entry(None, "JOURNAL_BY_DOI_NAMESPACE")


def _row(**overrides: object) -> JournalCorrectionRow:
    base: dict[str, object] = {
        "id": 1,
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
