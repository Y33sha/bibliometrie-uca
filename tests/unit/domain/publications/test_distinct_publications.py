"""Tests de la détection pure des cas de distinction (domain/publications/distinct_publications.py)."""

import pytest

from domain.publications.distinct_publications import (
    DistinctPublicationCase,
    detect_distinct_case,
)


def _detect(dt_a, dt_b, *, title_a="t", title_b="t"):
    return detect_distinct_case(
        doc_type_a=dt_a,
        title_normalized_a=title_a,
        doc_type_b=dt_b,
        title_normalized_b=title_b,
    )


class TestDetectDistinctCase:
    @pytest.mark.parametrize(("dt_a", "dt_b"), [("book", "book_chapter"), ("book_chapter", "book")])
    def test_ouvrage_vs_chapitre(self, dt_a, dt_b):
        assert _detect(dt_a, dt_b) == DistinctPublicationCase.OUVRAGE_VS_CHAPITRE

    def test_chapitres_titres_differents(self):
        assert (
            _detect("book_chapter", "book_chapter", title_a="intro", title_b="conclusion")
            == DistinctPublicationCase.CHAPITRES_TITRES_DIFFERENTS
        )

    def test_chapitres_meme_titre_non_distinct(self):
        # Deux chapitres au même titre (même DOI) = le même chapitre → fusionnable.
        assert _detect("book_chapter", "book_chapter", title_a="intro", title_b="intro") is None

    @pytest.mark.parametrize("these", ["thesis", "ongoing_thesis", "memoir"])
    def test_these_vs_article(self, these):
        assert _detect(these, "article") == DistinctPublicationCase.THESE_VS_ARTICLE
        assert _detect("article", these) == DistinctPublicationCase.THESE_VS_ARTICLE

    @pytest.mark.parametrize(
        ("dt_a", "dt_b"),
        [
            ("article", "article"),  # deux articles → fusionnable
            ("book", "book"),  # deux ouvrages
            ("thesis", "thesis"),  # deux thèses
            ("article", "preprint"),  # hors cas connus
            ("book", "thesis"),  # paire neutre
        ],
    )
    def test_no_case(self, dt_a, dt_b):
        assert _detect(dt_a, dt_b) is None

    def test_none_doc_types(self):
        assert _detect(None, None) is None

    def test_symmetric(self):
        assert _detect("book", "book_chapter") == _detect("book_chapter", "book")
