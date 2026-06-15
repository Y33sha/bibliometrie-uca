"""Tests purs : règle relationnelle ouvrage/chapitre + `compute_updates` (group-by-DOI)."""

from application.pipeline.metadata_correction.correct_by_cluster import compute_updates
from application.ports.pipeline.metadata_correction import DoiClusterRow, DoiCorrectionUpdate
from domain.source_publications.correction import (
    DistinctMergeCase,
    KeyGroupMember,
    detect_erroneous_key_holders,
)


def _row(id, doc_type, doi, raw_metadata=None, raw_doi="10.1/x") -> DoiClusterRow:
    return DoiClusterRow(id, doc_type, doi, raw_metadata or {}, raw_doi)


# ── domaine pur ──────────────────────────────────────────────────────────


def test_book_and_chapter_chapter_loses_key():
    group = [KeyGroupMember(1, "book"), KeyGroupMember(2, "book_chapter")]
    assert detect_erroneous_key_holders(group) == [(2, DistinctMergeCase.OUVRAGE_VS_CHAPITRE)]


def test_only_chapters_no_correction():
    # chapitre/chapitre est différé : pas de correction ici.
    assert (
        detect_erroneous_key_holders(
            [KeyGroupMember(1, "book_chapter"), KeyGroupMember(2, "book_chapter")]
        )
        == []
    )


def test_only_book_no_correction():
    assert detect_erroneous_key_holders([KeyGroupMember(1, "book")]) == []


# ── compute_updates (orchestration mécanique, group-by-DOI) ───────────────


def test_chapter_doi_nulled_book_untouched():
    book = _row(1, "book", "10.1/x")
    chapter = _row(2, "book_chapter", "10.1/x")
    updates = compute_updates([book, chapter])
    assert updates == [
        DoiCorrectionUpdate(
            2, None, {"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}}
        )
    ]


def test_idempotent_when_already_nulled():
    book = _row(1, "book", "10.1/x")
    chapter = _row(
        2,
        "book_chapter",
        None,
        {"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    assert compute_updates([book, chapter]) == []


def test_self_heals_when_book_gone():
    # Chapitre déjà nullé, mais plus d'ouvrage dans le groupe → DOI restauré.
    chapter = _row(
        2,
        "book_chapter",
        None,
        {"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    assert compute_updates([chapter]) == [DoiCorrectionUpdate(2, "10.1/x", {})]


def test_preserves_unmanaged_raw_metadata_keys():
    # La clé `doc_type` (gérée par la passe unaire) doit survivre au nullage du DOI.
    book = _row(1, "book", "10.1/x")
    chapter = _row(
        2, "book_chapter", "10.1/x", {"doc_type": {"raw": "COUV", "corrected_by": "DOC_TYPE_MAP"}}
    )
    updates = compute_updates([book, chapter])
    assert updates[0].raw_metadata == {
        "doc_type": {"raw": "COUV", "corrected_by": "DOC_TYPE_MAP"},
        "doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"},
    }


def test_chapters_in_separate_doi_groups_isolated():
    # Deux groupes DOI distincts : chacun évalué indépendamment.
    g1 = [
        _row(1, "book", "10.1/a", raw_doi="10.1/a"),
        _row(2, "book_chapter", "10.1/a", raw_doi="10.1/a"),
    ]
    g2 = [_row(3, "book_chapter", "10.1/b", raw_doi="10.1/b")]  # pas d'ouvrage → rien
    updates = compute_updates(g1 + g2)
    assert {u.id for u in updates} == {2}
