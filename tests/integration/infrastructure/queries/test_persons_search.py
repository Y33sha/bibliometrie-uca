"""Recherche de personnes par nom : chaque mot saisi figure dans le nom ou le prénom.

L'annuaire et l'autocomplétion appliquent la même règle : prénom et nom se saisissent ensemble, dans n'importe quel ordre, sans tenir compte des accents."""

import pytest
from sqlalchemy import text

from application.ports.read_models.persons_queries import PersonFilters
from infrastructure.read_models.persons.list import list_persons, search_persons


def _create_person(conn, last, first):
    return (
        conn.execute(
            text(
                "INSERT INTO persons "
                "(last_name, first_name, last_name_normalized, first_name_normalized) "
                "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
            ),
            {"l": last, "f": first},
        )
        .one()
        .id
    )


def _directory_ids(conn, search):
    result = list_persons(
        conn, filters=PersonFilters(search=search), page=1, per_page=1000, sort="name_asc"
    )
    return {p.id for p in result.persons}


def _autocomplete_ids(conn, search):
    return {p.id for p in search_persons(conn, search=search, limit=30)}


@pytest.fixture
def people(sa_sync_conn):
    return {
        "legue": _create_person(sa_sync_conn, "Legué", "Valérie"),
        "martin": _create_person(sa_sync_conn, "Martin", "Valérie"),
    }


@pytest.mark.parametrize("lecture", [_directory_ids, _autocomplete_ids])
class TestSearchByName:
    @pytest.mark.parametrize("search", ["Valérie Legué", "Legué Valérie", "valerie legue"])
    def test_prenom_et_nom_ensemble(self, sa_sync_conn, people, lecture, search):
        found = lecture(sa_sync_conn, search)
        assert people["legue"] in found
        assert people["martin"] not in found

    def test_un_seul_mot_suffit(self, sa_sync_conn, people, lecture):
        found = lecture(sa_sync_conn, "Valérie")
        assert {people["legue"], people["martin"]} <= found
