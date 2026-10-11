"""Tests de l'aggregate root `Person` (scaffolding Phase 1)."""

import pytest

from domain.errors import ConflictError
from domain.persons.identifier_attribution import IdentifierAttribution
from domain.persons.identifiers import AttributionStatus
from domain.persons.name_forms import PersonNameForm
from domain.persons.person import Person, merge_roles


def _make_person(person_id: int | None = 1) -> Person:
    return Person(
        id=person_id,
        last_name="Dupont",
        first_name="Jean",
        last_name_normalized="dupont",
        first_name_normalized="jean",
    )


class TestPersonConstruction:
    def test_accepts_minimal_args(self):
        p = _make_person()
        assert p.id == 1
        assert p.exclusion is None
        assert p.identifiers == ()
        assert p.name_forms == ()

    def test_accepts_identifiers_and_name_forms(self):
        ident = IdentifierAttribution(
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


class TestMergeRoles:
    def test_keeps_requested_roles_without_rh(self):
        assert merge_roles(1, 2, with_rh=set()) == (1, 2)

    def test_keeps_requested_roles_when_target_has_rh(self):
        assert merge_roles(1, 2, with_rh={1}) == (1, 2)

    def test_swaps_roles_when_only_source_has_rh(self):
        assert merge_roles(1, 2, with_rh={2}) == (2, 1)

    def test_raises_when_both_have_rh(self):
        with pytest.raises(ConflictError, match="#42.*#17.*fiche RH"):
            merge_roles(42, 17, with_rh={42, 17})
