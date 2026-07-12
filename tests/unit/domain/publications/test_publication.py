"""Tests de l'aggregate root `Publication`."""

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
