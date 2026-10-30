"""Tests de l'entité `Publication`."""

from domain.publications.identifiers import DOI
from domain.publications.publication import Publication


class TestPublicationConstruction:
    def test_accepts_minimal_args(self):
        publication = Publication(id=None, title="A paper", publication_year=2024)
        assert publication.id is None
        assert publication.title == "A paper"
        assert publication.publication_year == 2024
        assert publication.doi is None

    def test_accepts_doi_vo(self):
        publication = Publication(id=1, title="t", publication_year=2024, doi=DOI("10.1234/test"))
        assert publication.doi == DOI("10.1234/test")
