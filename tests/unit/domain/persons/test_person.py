"""Tests de l'aggregate root ``Person`` (scaffolding Phase 1)."""

import pytest

from domain.errors import ConflictError
from domain.persons.identifiers import AttributionStatus
from domain.persons.name_forms import PersonNameForm
from domain.persons.person import Person
from domain.persons.person_identifier import PersonIdentifier


def _make_person(id: int | None = 1) -> Person:
    return Person(
        id=id,
        last_name="Dupont",
        first_name="Jean",
        last_name_normalized="dupont",
        first_name_normalized="jean",
    )


class TestPersonConstruction:
    def test_accepts_minimal_args(self):
        p = _make_person()
        assert p.id == 1
        assert p.rejected is False
        assert p.identifiers == ()
        assert p.name_forms == ()

    def test_accepts_identifiers_and_name_forms(self):
        ident = PersonIdentifier(
            id=1,
            person_id=10,
            id_type="orcid",
            id_value="0000-0000-0000-0001",
            status=AttributionStatus.CONFIRMED,
        )
        nf = PersonNameForm("dupont jean")
        p = Person(
            id=10,
            last_name="Dupont",
            first_name="Jean",
            last_name_normalized="dupont",
            first_name_normalized="jean",
            identifiers=(ident,),
            name_forms=(nf,),
        )
        assert p.identifiers == (ident,)
        assert p.name_forms == (nf,)


class TestCanMergeWith:
    def test_ok_when_no_distinct_rh(self):
        a = _make_person(id=1)
        b = _make_person(id=2)
        a.can_merge_with(b, has_distinct_rh=False)  # ne lève pas

    def test_raises_when_distinct_rh(self):
        a = _make_person(id=1)
        b = _make_person(id=2)
        with pytest.raises(ConflictError, match="fiche RH"):
            a.can_merge_with(b, has_distinct_rh=True)
