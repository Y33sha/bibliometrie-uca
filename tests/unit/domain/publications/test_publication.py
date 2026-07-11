"""Tests de l'aggregate root `Publication`."""

import pytest

from domain.errors import ConflictError
from domain.publications.authorship import Authorship
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication


def _pub(**kwargs) -> Publication:
    """Helper : construit une Publication avec des valeurs par défaut sûres pour les tests d'absorb."""
    defaults = dict(id=1, title="t", pub_year=2024)
    defaults.update(kwargs)
    return Publication(**defaults)


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


class TestPublicationAbsorb:
    def test_target_keeps_existing_doi(self):
        target = _pub(id=1, doi=DOI("10.1/keep"))
        source = _pub(id=2, doi=DOI("10.2/other"))
        target.absorb(source)
        assert target.doi == DOI("10.1/keep")

    def test_target_inherits_doi_when_absent(self):
        target = _pub(id=1, doi=None)
        source = _pub(id=2, doi=DOI("10.2/from-source"))
        target.absorb(source)
        assert target.doi == DOI("10.2/from-source")

    def test_target_inherits_other_scalars_when_absent(self):
        target = _pub(id=1, journal_id=None, container_title=None, language=None)
        source = _pub(
            id=2,
            journal_id=42,
            container_title="J. of Tests",
            language="en",
        )
        target.absorb(source)
        assert target.journal_id == 42
        assert target.container_title == "J. of Tests"
        assert target.language == "en"

    def test_target_keeps_scalars_when_present(self):
        target = _pub(id=1, journal_id=10, container_title="Target Journal", language="fr")
        source = _pub(id=2, journal_id=99, container_title="Other Journal", language="en")
        target.absorb(source)
        assert target.journal_id == 10
        assert target.container_title == "Target Journal"
        assert target.language == "fr"

    def test_oa_status_uses_absorb_rule(self):
        """Délègue à absorb_oa_status : target=closed + source=green → green."""
        target = _pub(id=1, oa_status="closed")
        source = _pub(id=2, oa_status="green")
        target.absorb(source)
        assert target.oa_status == "green"

    def test_oa_status_target_open_stays(self):
        """target=hybrid + source=gold : target reste hybrid (cf. règle pairwise)."""
        target = _pub(id=1, oa_status="hybrid")
        source = _pub(id=2, oa_status="gold")
        target.absorb(source)
        assert target.oa_status == "hybrid"

    def test_countries_union_preserves_order(self):
        target = _pub(id=1, countries=("FR", "IT"))
        source = _pub(id=2, countries=("IT", "DE", "FR"))
        target.absorb(source)
        # FR, IT d'abord (ordre target), puis DE (nouveau de source).
        assert target.countries == ("FR", "IT", "DE")

    def test_countries_empty_target_takes_source(self):
        target = _pub(id=1, countries=())
        source = _pub(id=2, countries=("FR",))
        target.absorb(source)
        assert target.countries == ("FR",)

    def test_authorships_not_touched(self):
        """Les authorships restent inchangées sur target (le repo les déplace)."""
        a = Authorship(id=None, publication_id=1, person_id=10)
        target = _pub(id=1, authorships=(a,))
        source = _pub(id=2, authorships=())
        target.absorb(source)
        assert target.authorships == (a,)

    def test_id_preserved(self):
        target = _pub(id=1, doi=None)
        source = _pub(id=2, doi=DOI("10.1/x"))
        target.absorb(source)
        assert target.id == 1  # target garde son identité

    def test_raises_on_self_absorb(self):
        target = _pub(id=42)
        same = _pub(id=42)
        with pytest.raises(ConflictError, match="absorber elle-même"):
            target.absorb(same)

    def test_none_ids_dont_raise_on_self_check(self):
        """Deux publications non persistées (id=None) peuvent légalement
        être absorbées entre elles — None != None côté identité métier."""
        target = _pub(id=None, doi=None)
        source = _pub(id=None, doi=DOI("10.1/x"))
        target.absorb(source)  # ne lève pas
        assert target.doi == DOI("10.1/x")
