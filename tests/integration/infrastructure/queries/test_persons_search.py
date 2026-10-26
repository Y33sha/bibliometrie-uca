"""Recherche de personnes par nom : chaque mot saisi figure dans le nom ou le prénom.

L'annuaire et l'autocomplétion appliquent la même règle : prénom et nom se saisissent ensemble, dans n'importe quel ordre, sans tenir compte des accents."""

import pytest

from infrastructure.read_models.persons.models import PersonFilters
from infrastructure.read_models.persons.queries import PersonsQueries
from tests.integration.helpers.persons import insert_person


def _directory_ids(conn, search):
    result = PersonsQueries(conn).list_persons(
        filters=PersonFilters(search=search), page=1, per_page=1000, sort="name_asc"
    )
    return {p.id for p in result.persons}


def _autocomplete_ids(conn, search):
    return {p.id for p in PersonsQueries(conn).search_persons(search=search, limit=30)}


@pytest.fixture
def people(sa_sync_conn):
    return {
        "legue": insert_person(sa_sync_conn, "Legué", first_name="Valérie"),
        "martin": insert_person(sa_sync_conn, "Martin", first_name="Valérie"),
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
