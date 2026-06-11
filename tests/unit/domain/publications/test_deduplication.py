"""Tests unitaires de `domain.publications.deduplication`.

Couvre `detect_metadata_merge_case` (règle pure de fusion par métadonnées). La
compatibilité d'auteur passe par la vraie fonction `thesis_authors_compatible`.
"""

from domain.publications.deduplication import (
    MetadataDeduplicationCase,
    detect_metadata_merge_case,
)

# ── Thèse ─────────────────────────────────────────────────────────


def _thesis(**kw):
    return detect_metadata_merge_case(
        doc_type_a="thesis", doc_type_b="thesis", title_normalized="une these", **kw
    )


def test_thesis_compatible_authors_merge():
    assert (
        _thesis(
            thesis_primary_author_a=("Dupont", "Jean"),
            thesis_primary_author_b=("Dupont", "J"),
        )
        is MetadataDeduplicationCase.THESIS_TITLE_YEAR
    )


def test_thesis_incompatible_authors_no_merge():
    assert (
        _thesis(
            thesis_primary_author_a=("Dupont", "Jean"),
            thesis_primary_author_b=("Martin", "Paul"),
        )
        is None
    )


def test_thesis_unknown_author_one_side_merges():
    assert (
        _thesis(thesis_primary_author_a=("Dupont", "Jean"), thesis_primary_author_b=None)
        is MetadataDeduplicationCase.THESIS_TITLE_YEAR
    )


def test_thesis_and_ongoing_thesis_same_family():
    assert (
        detect_metadata_merge_case(
            doc_type_a="thesis",
            doc_type_b="ongoing_thesis",
            title_normalized="t",
            thesis_primary_author_a=None,
            thesis_primary_author_b=None,
        )
        is MetadataDeduplicationCase.THESIS_TITLE_YEAR
    )


# ── Proceedings ───────────────────────────────────────────────────


def _proceedings(title="x" * 40, **kw):
    return detect_metadata_merge_case(
        doc_type_a="proceedings", doc_type_b="proceedings", title_normalized=title, **kw
    )


def test_proceedings_same_count_long_title_merges():
    assert (
        _proceedings(author_count_a=5, author_count_b=5)
        is MetadataDeduplicationCase.PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT
    )


def test_proceedings_short_title_no_merge():
    assert _proceedings(title="court", author_count_a=5, author_count_b=5) is None


def test_proceedings_different_count_no_merge():
    assert _proceedings(author_count_a=5, author_count_b=7) is None


# ── Autres doc_types ──────────────────────────────────────────────


def test_article_no_case():
    assert (
        detect_metadata_merge_case(
            doc_type_a="article", doc_type_b="article", title_normalized="x" * 40
        )
        is None
    )


def test_mixed_family_no_case():
    assert (
        detect_metadata_merge_case(
            doc_type_a="thesis", doc_type_b="proceedings", title_normalized="x" * 40
        )
        is None
    )
