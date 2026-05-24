"""Tests unitaires de `application.pipeline.publications.metadata_deduplication_rules`.

Mocks : port `PublicationsMatchOrCreateQueries`, `PublicationRepository`. `thesis_authors_compatible` monkeypatché dans le module pour isoler la logique.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from application.pipeline.publications import metadata_deduplication_rules
from application.pipeline.publications.metadata_deduplication_rules import (
    match_proceedings_by_title_year_authorcount,
    match_thesis_by_title_year,
)
from domain.publications.deduplication import MetadataDeduplicationCase


class TestMatchThesisByTitleYear:
    def test_empty_title_returns_none(self):
        queries = MagicMock()
        repo = MagicMock()

        result = match_thesis_by_title_year(
            conn=None,
            queries=queries,
            source_publication_id=1,
            title_normalized="",
            pub_year=2024,
            pub_repo=repo,
        )

        assert result is None
        repo.find_thesis_by_title.assert_not_called()

    def test_missing_pub_year_returns_none(self):
        queries = MagicMock()
        repo = MagicMock()

        result = match_thesis_by_title_year(
            conn=None,
            queries=queries,
            source_publication_id=1,
            title_normalized="some title",
            pub_year=0,
            pub_repo=repo,
        )

        assert result is None
        repo.find_thesis_by_title.assert_not_called()

    def test_no_candidates_returns_none(self):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_thesis_by_title.return_value = []

        result = match_thesis_by_title_year(
            conn=None,
            queries=queries,
            source_publication_id=1,
            title_normalized="title",
            pub_year=2024,
            pub_repo=repo,
        )

        assert result is None

    def test_source_has_no_author_accepts_first_candidate(self):
        """Quand l'auteur du source_publication est inconnu, le 1er candidat passe sans vérif (préserve le comportement historique)."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_thesis_by_title.return_value = [42]
        queries.fetch_thesis_primary_author_from_source_publication.return_value = None

        result = match_thesis_by_title_year(
            conn=None,
            queries=queries,
            source_publication_id=1,
            title_normalized="title",
            pub_year=2024,
            pub_repo=repo,
        )

        assert result == (42, MetadataDeduplicationCase.THESIS_TITLE_YEAR)
        # fetch_thesis_primary_author est appelée mais sa valeur n'est pas comparée.
        queries.fetch_thesis_primary_author.assert_called_once()

    def test_first_incompatible_second_compatible(self, monkeypatch):
        """Itère sur les candidats jusqu'à trouver un auteur compatible."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_thesis_by_title.return_value = [10, 20]
        queries.fetch_thesis_primary_author_from_source_publication.return_value = (
            "Doe",
            "Jane",
        )
        # 1er candidat : auteur incompatible. 2e : compatible.
        queries.fetch_thesis_primary_author.side_effect = [
            ("Smith", "John"),
            ("Doe", "J"),
        ]

        # Stubber `thesis_authors_compatible` : False pour Smith, True pour Doe.
        def fake_compat(a, b):
            return a == ("Doe", "J")

        monkeypatch.setattr(metadata_deduplication_rules, "thesis_authors_compatible", fake_compat)

        result = match_thesis_by_title_year(
            conn=None,
            queries=queries,
            source_publication_id=1,
            title_normalized="title",
            pub_year=2024,
            pub_repo=repo,
        )

        assert result == (20, MetadataDeduplicationCase.THESIS_TITLE_YEAR)

    def test_all_incompatible_returns_none(self, monkeypatch):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_thesis_by_title.return_value = [10, 20]
        queries.fetch_thesis_primary_author_from_source_publication.return_value = (
            "Doe",
            "Jane",
        )
        queries.fetch_thesis_primary_author.side_effect = [("X", "Y"), ("Z", "W")]
        monkeypatch.setattr(
            metadata_deduplication_rules,
            "thesis_authors_compatible",
            lambda a, b: False,
        )

        result = match_thesis_by_title_year(
            conn=None,
            queries=queries,
            source_publication_id=1,
            title_normalized="title",
            pub_year=2024,
            pub_repo=repo,
        )

        assert result is None


_LONG_TITLE = "frailty onset predictions using sleep analysis"  # 46 car > 30


def _call_proceedings(
    *,
    queries: MagicMock,
    repo: MagicMock,
    doi: str | None = None,
    title: str = _LONG_TITLE,
    pub_year: int = 2022,
) -> tuple[int, MetadataDeduplicationCase] | None:
    return match_proceedings_by_title_year_authorcount(
        conn=None,
        queries=queries,
        source_publication_id=1,
        title_normalized=title,
        pub_year=pub_year,
        doi=doi,
        pub_repo=repo,
    )


class TestMatchProceedingsByTitleYearAuthorcount:
    def test_no_candidates_returns_none(self):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_proceedings_by_title_year.return_value = []

        assert _call_proceedings(queries=queries, repo=repo) is None
        queries.fetch_source_authorship_count.assert_not_called()

    def test_match_when_counts_equal(self):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_proceedings_by_title_year.return_value = [(42, None)]
        queries.fetch_source_authorship_count.return_value = 7
        queries.fetch_max_source_authorship_count_per_publication.return_value = 7

        assert _call_proceedings(queries=queries, repo=repo) == (
            42,
            MetadataDeduplicationCase.PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT,
        )

    def test_count_diff_returns_none(self):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_proceedings_by_title_year.return_value = [(42, None)]
        queries.fetch_source_authorship_count.return_value = 7
        queries.fetch_max_source_authorship_count_per_publication.return_value = 6

        assert _call_proceedings(queries=queries, repo=repo) is None

    def test_iterates_until_matching_count(self):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_proceedings_by_title_year.return_value = [(10, None), (20, None)]
        queries.fetch_source_authorship_count.return_value = 7
        queries.fetch_max_source_authorship_count_per_publication.side_effect = [5, 7]

        assert _call_proceedings(queries=queries, repo=repo) == (
            20,
            MetadataDeduplicationCase.PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT,
        )

    def test_both_dois_non_null_skips_candidate(self):
        """SP avec DOI A + candidate avec DOI B = forcément différents (UNIQUE) → conflit."""
        queries = MagicMock()
        repo = MagicMock()
        repo.find_proceedings_by_title_year.return_value = [(42, "10.x/y")]
        queries.fetch_source_authorship_count.return_value = 7

        assert _call_proceedings(queries=queries, repo=repo, doi="10.x/z") is None
        queries.fetch_max_source_authorship_count_per_publication.assert_not_called()

    def test_sp_doi_candidate_no_doi_match(self):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_proceedings_by_title_year.return_value = [(42, None)]
        queries.fetch_source_authorship_count.return_value = 7
        queries.fetch_max_source_authorship_count_per_publication.return_value = 7

        assert _call_proceedings(queries=queries, repo=repo, doi="10.x/y") == (
            42,
            MetadataDeduplicationCase.PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT,
        )

    def test_skip_candidate_with_doi_then_match_next(self):
        queries = MagicMock()
        repo = MagicMock()
        repo.find_proceedings_by_title_year.return_value = [(10, "10.x/y"), (20, None)]
        queries.fetch_source_authorship_count.return_value = 7
        queries.fetch_max_source_authorship_count_per_publication.return_value = 7

        assert _call_proceedings(queries=queries, repo=repo, doi="10.x/z") == (
            20,
            MetadataDeduplicationCase.PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT,
        )
