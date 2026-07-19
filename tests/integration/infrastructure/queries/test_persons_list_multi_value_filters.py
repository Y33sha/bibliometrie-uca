"""Régression : la liste admin filtre sur plusieurs départements ou rôles.

L'annuaire public et les facettes acceptaient une sélection multiple là où la liste admin
n'acceptait qu'une valeur. La page cochant plusieurs options, ses compteurs de facettes
reflétaient la sélection pendant que la liste montrait tout le monde.
"""

from sqlalchemy import text

from application.ports.api.persons_queries import ListFilters
from infrastructure.queries.api.persons.list import list_persons


def _create_person(conn, last, department=None, role=None):
    person_id = (
        conn.execute(
            text(
                "INSERT INTO persons "
                "(last_name, first_name, last_name_normalized, first_name_normalized) "
                "VALUES (:l, 'Z', lower(:l), 'z') RETURNING id"
            ),
            {"l": last},
        )
        .one()
        .id
    )
    if department or role:
        conn.execute(
            text(
                "INSERT INTO persons_rh (person_id, email, department_name, role_title) "
                "VALUES (:pid, :mail, :dept, :role)"
            ),
            {
                "pid": person_id,
                "mail": f"{last.lower()}@uca.fr",
                "dept": department,
                "role": role,
            },
        )
    return person_id


def _listed(conn, **filter_kwargs):
    result = list_persons(
        conn, filters=ListFilters(**filter_kwargs), page=1, per_page=200, sort="name_asc"
    )
    return {p["id"] for p in result["persons"]}


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
