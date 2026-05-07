"""Tests des règles de déduplication / création des publications."""

from domain.publications.dedup import has_minimal_publication_metadata


class TestHasMinimalPublicationMetadata:
    def test_title_and_year_present(self):
        assert has_minimal_publication_metadata("Some title", 2024) is True

    def test_missing_title(self):
        assert has_minimal_publication_metadata(None, 2024) is False
        assert has_minimal_publication_metadata("", 2024) is False

    def test_missing_year(self):
        assert has_minimal_publication_metadata("Some title", None) is False

    def test_year_zero_treated_as_missing(self):
        """Année 0 : cas pathologique, on traite comme absente."""
        assert has_minimal_publication_metadata("Some title", 0) is False

    def test_both_missing(self):
        assert has_minimal_publication_metadata(None, None) is False
