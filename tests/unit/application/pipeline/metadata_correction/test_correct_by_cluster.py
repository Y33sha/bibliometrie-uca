"""Tests purs : règles relationnelles (ouvrage/chapitre, chapitre/chapitre) + `compute_updates`."""

from application.pipeline.metadata_correction.correct_by_cluster import compute_updates
from application.ports.pipeline.metadata_correction import DoiClusterRow, DoiCorrectionUpdate
from domain.source_publications.correction import (
    DistinctMergeCase,
    KeyGroupMember,
    detect_erroneous_key_holders,
)


def _row(id, doc_type, doi, title="t", raw_metadata=None, raw_doi="10.1/x") -> DoiClusterRow:
    return DoiClusterRow(id, doc_type, doi, title, raw_metadata or {}, raw_doi)


def _m(id, doc_type, title="t") -> KeyGroupMember:
    return KeyGroupMember(id, doc_type, title)


# ── domaine pur : ouvrage/chapitre ───────────────────────────────────────


def test_book_and_chapter_chapter_loses_key():
    group = [_m(1, "book"), _m(2, "book_chapter")]
    assert detect_erroneous_key_holders(group) == [(2, DistinctMergeCase.OUVRAGE_VS_CHAPITRE)]


def test_only_book_no_correction():
    assert detect_erroneous_key_holders([_m(1, "book")]) == []


# ── domaine pur : chapitre/chapitre (nettoyage + containment + strict) ────


def test_chapters_distinct_titles_all_lose_key():
    group = [
        _m(1, "book_chapter", "geographie de l environnement"),
        _m(2, "book_chapter", "le monde a la une"),
    ]
    cases = detect_erroneous_key_holders(group)
    assert {c for _, c in cases} == {DistinctMergeCase.CHAPITRES_TITRES_DIFFERENTS}
    assert {i for i, _ in cases} == {1, 2}


def test_chapters_same_title_no_correction():
    # Même chapitre, deux sources : titres identiques → pas de conflit.
    assert (
        detect_erroneous_key_holders(
            [_m(1, "book_chapter", "introduction"), _m(2, "book_chapter", "introduction")]
        )
        == []
    )


def test_chapters_chapter_number_prefix_is_same():
    # « chapitre 14 X » vs « X » : même chapitre (marqueur + numéro retirés) → pas de conflit.
    g = [
        _m(1, "book_chapter", "chapitre 14 les limnosystemes"),
        _m(2, "book_chapter", "les limnosystemes"),
    ]
    assert detect_erroneous_key_holders(g) == []


def test_chapters_subtitle_truncation_is_same():
    # Troncature de sous-titre : « titre sous titre » contient « titre » → même chapitre.
    g = [
        _m(1, "book_chapter", "contested concepts"),
        _m(2, "book_chapter", "contested concepts plutarch on common notions"),
    ]
    assert detect_erroneous_key_holders(g) == []


def test_chapters_typo_is_false_positive_left_to_admin():
    # Coquille (1 lettre) : NON capturée par le déterministe (pas de fuzzy) → flag (FP assumé, admin).
    g = [
        _m(1, "book_chapter", "les effets thermomecaniques"),
        _m(2, "book_chapter", "les effets thermomecanqiues"),
    ]
    assert detect_erroneous_key_holders(g) != []  # comportement assumé : déterministe, pas de fuzzy


# ── compute_updates (orchestration mécanique) ────────────────────────────


def test_chapter_doi_nulled_book_untouched():
    book = _row(1, "book", "10.1/x")
    chapter = _row(2, "book_chapter", "10.1/x")
    assert compute_updates([book, chapter]) == [
        DoiCorrectionUpdate(
            2, None, {"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}}
        )
    ]


def test_chapter_chapter_both_nulled():
    a = _row(1, "book_chapter", "10.1/x", title="premier chapitre distinct")
    b = _row(2, "book_chapter", "10.1/x", title="second chapitre autre")
    updates = compute_updates([a, b])
    assert {u.id for u in updates} == {1, 2}
    assert all(u.doi is None for u in updates)
    assert all(
        u.raw_metadata["doi"]["corrected_by"] == "CHAPITRES_TITRES_DIFFERENTS" for u in updates
    )


def test_idempotent_when_already_nulled():
    book = _row(1, "book", "10.1/x")
    chapter = _row(
        2,
        "book_chapter",
        None,
        raw_metadata={"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    assert compute_updates([book, chapter]) == []


def test_self_heals_when_book_gone():
    chapter = _row(
        2,
        "book_chapter",
        None,
        raw_metadata={"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}},
    )
    assert compute_updates([chapter]) == [DoiCorrectionUpdate(2, "10.1/x", {})]
