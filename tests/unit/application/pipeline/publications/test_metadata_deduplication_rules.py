"""Tests unitaires de `application.pipeline.publications.metadata_deduplication_rules`.

Mocks : port `PublicationsMatchOrCreateQueries`, `PublicationRepository`. `thesis_authors_compatible` monkeypatché dans le module pour isoler la logique.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from application.pipeline.publications import metadata_deduplication_rules
from application.pipeline.publications.metadata_deduplication_rules import (
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
