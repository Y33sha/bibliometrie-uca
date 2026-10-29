"""Tests de l'aggregate root `Person`."""

from domain.persons.identifier_attribution import IdentifierAttribution
from domain.persons.identifiers import AttributionStatus
from domain.persons.name_forms import PersonNameForm
from domain.persons.person import Person


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
        name_form = PersonNameForm("dupont jean")
        p = Person(
            id=10,
            last_name="Dupont",
            first_name="Jean",
            last_name_normalized="dupont",
            first_name_normalized="jean",
            identifiers=(ident,),
            name_forms=(name_form,),
        )
        assert p.identifiers == (ident,)
        assert p.name_forms == (name_form,)
