"""Régression : la liste admin filtre sur plusieurs départements ou rôles.

L'annuaire public et les facettes acceptaient une sélection multiple là où la liste admin
n'acceptait qu'une valeur. La page cochant plusieurs options, ses compteurs de facettes
reflétaient la sélection pendant que la liste montrait tout le monde.
"""

from infrastructure.read_models.persons.models import PersonFilters
from infrastructure.read_models.persons.queries import PersonsQueries
from tests.integration.helpers.persons import insert_hr_record, insert_person


def _create_person(conn, last, department=None, role=None):
    """Personne, avec sa fiche RH quand un département ou un rôle est donné."""
    person_id = insert_person(conn, last)
    if department or role:
        insert_hr_record(
            conn,
            person_id,
            email=f"{last.lower()}@uca.fr",
            department_name=department,
            role_title=role,
        )
    return person_id


def _listed(conn, **filter_kwargs):
    result = PersonsQueries(conn).list_persons(
        filters=PersonFilters(**filter_kwargs), page=1, per_page=200, sort="name_asc"
    )
    return {p.id for p in result.persons}


class TestListMultiValueFilters:
    def test_filters_on_several_departments(self, sa_sync_conn):
        math = _create_person(sa_sync_conn, "Mathy", department="UFR Math")
        bio = _create_person(sa_sync_conn, "Bioly", department="UFR Biologie")
        droit = _create_person(sa_sync_conn, "Droity", department="Ecole Droit")

        listed = _listed(sa_sync_conn, departments=["UFR Math", "UFR Biologie"])

        assert {math, bio} <= listed
        assert droit not in listed

    def test_filters_on_several_roles(self, sa_sync_conn):
        pr = _create_person(sa_sync_conn, "Proffy", role="PR")
        mcf = _create_person(sa_sync_conn, "Emcefy", role="MCF")
        ater = _create_person(sa_sync_conn, "Atery", role="ATER")

        listed = _listed(sa_sync_conn, roles=["PR", "MCF"])

        assert {pr, mcf} <= listed
        assert ater not in listed

    def test_empty_selection_filters_nothing(self, sa_sync_conn):
        someone = _create_person(sa_sync_conn, "Nobodyy", department="UFR Math")
        assert someone in _listed(sa_sync_conn, departments=[], roles=[])
