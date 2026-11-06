"""La liste des personnes filtre sur plusieurs catégories ou laboratoires actuels, comme ses facettes, et affiche le laboratoire de chaque personne."""

import datetime

from sqlalchemy import text

from infrastructure.read_models.persons.models import PersonFilters, PersonLaboratoryOut
from infrastructure.read_models.persons.queries import PersonsQueries
from tests.integration.helpers.persons import insert_hr_period, insert_hr_record, insert_person
from tests.integration.helpers.structures import insert_structure

D = datetime.date


def _create_person(conn, last, *, category=None):
    """Insère une personne et sa fiche RH."""
    person_id = insert_person(conn, last)
    insert_hr_record(conn, person_id, email=f"{last.lower()}@uca.fr")
    conn.execute(
        text("UPDATE hr_records SET staff_category = :c WHERE person_id = :p"),
        {"c": category, "p": person_id},
    )
    return person_id


def _list(conn, **filter_kwargs):
    return PersonsQueries(conn).list_persons(
        filters=PersonFilters(**filter_kwargs), page=1, per_page=200, sort="name_asc"
    )


def _listed(conn, **filter_kwargs):
    return {p.id for p in _list(conn, **filter_kwargs).persons}


class TestListMultiValueFilters:
    def test_filters_on_several_categories(self, sa_sync_conn):
        ens = _create_person(sa_sync_conn, "Ensy", category="ENSEIG")
        biatss = _create_person(sa_sync_conn, "Biatssy", category="BIATSS")
        other = _create_person(sa_sync_conn, "Othery", category="AUTRE")

        listed = _listed(sa_sync_conn, categories=["ENSEIG", "BIATSS"])

        assert {ens, biatss} <= listed
        assert other not in listed

    def test_filters_on_current_laboratory(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB-CUR", acronym="LABCUR")
        present = _create_person(sa_sync_conn, "Presenty")
        insert_hr_period(sa_sync_conn, present, unit_label="LABCUR", structure_id=lab)
        gone = _create_person(sa_sync_conn, "Goney")
        insert_hr_period(
            sa_sync_conn, gone, unit_label="LABCUR", structure_id=lab, end_date=D(2020, 1, 1)
        )

        listed = _listed(sa_sync_conn, laboratories=[lab])

        assert present in listed
        assert gone not in listed

    def test_empty_selection_filters_nothing(self, sa_sync_conn):
        someone = _create_person(sa_sync_conn, "Nobodyy", category="ENSEIG")
        assert someone in _listed(sa_sync_conn, categories=[], laboratories=[])


class TestLaboratoryDisplay:
    def test_current_laboratories(self, sa_sync_conn):
        lab = insert_structure(sa_sync_conn, "LAB-DISP", acronym="LABDISP")
        person = _create_person(sa_sync_conn, "Displayy")
        insert_hr_period(sa_sync_conn, person, unit_label="UFR X", start_date=D(2010, 1, 1))
        insert_hr_period(sa_sync_conn, person, unit_label="LABDISP - A", structure_id=lab)
        insert_hr_period(sa_sync_conn, person, unit_label="LABDISP - B", structure_id=lab)

        [row] = _list(sa_sync_conn, search="displayy").persons

        assert row.laboratories == [PersonLaboratoryOut(id=lab, label="LABDISP", current=True)]

    def test_last_laboratory_of_a_departed_person(self, sa_sync_conn):
        old = insert_structure(sa_sync_conn, "LAB-OLD", acronym="LABOLD")
        last = insert_structure(sa_sync_conn, "LAB-LAST", acronym="LABLAST")
        person = _create_person(sa_sync_conn, "Departy")
        insert_hr_period(
            sa_sync_conn, person, unit_label="LABOLD", structure_id=old, end_date=D(2015, 1, 1)
        )
        insert_hr_period(
            sa_sync_conn, person, unit_label="LABLAST", structure_id=last, end_date=D(2020, 1, 1)
        )

        [row] = _list(sa_sync_conn, search="departy").persons

        assert row.laboratories == [PersonLaboratoryOut(id=last, label="LABLAST", current=False)]
