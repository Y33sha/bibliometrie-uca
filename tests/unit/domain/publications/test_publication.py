"""Tests de l'aggregate root ``Publication`` (scaffolding Phase 1)."""

from domain.publications.authorship import Authorship
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication


class TestPublicationConstruction:
    def test_accepts_minimal_args(self):
        pub = Publication(id=None, title="A paper", pub_year=2024)
        assert pub.id is None
        assert pub.title == "A paper"
        assert pub.pub_year == 2024
        assert pub.doi is None
        assert pub.authorships == ()

    def test_accepts_doi_vo(self):
        pub = Publication(id=1, title="t", pub_year=2024, doi=DOI("10.1234/test"))
        assert pub.doi == DOI("10.1234/test")

    def test_accepts_authorships_tuple(self):
        a1 = Authorship(id=None, publication_id=1, person_id=10)
        a2 = Authorship(id=None, publication_id=1, person_id=20)
        pub = Publication(id=1, title="t", pub_year=2024, authorships=(a1, a2))
        assert pub.authorships == (a1, a2)


class TestPublicationHasMinimalMetadata:
    def test_true_when_title_and_year(self):
        assert Publication(id=None, title="t", pub_year=2024).has_minimal_metadata() is True

    def test_false_when_empty_title(self):
        assert Publication(id=None, title="", pub_year=2024).has_minimal_metadata() is False

    def test_false_when_year_zero(self):
        """Convention : pub_year=0 → cas pathologique, considéré absent."""
        assert Publication(id=None, title="t", pub_year=0).has_minimal_metadata() is False
