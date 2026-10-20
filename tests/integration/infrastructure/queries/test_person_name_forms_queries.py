"""Tests d'intégration des requêtes de `pipeline.transformation.persons.populate_person_name_forms`."""

from sqlalchemy import text

from pipeline.transformation.persons.populate_person_name_forms import (
    create_temp_raw_forms_table,
    drop_temp_raw_forms_table,
    fetch_persons_names,
    insert_raw_forms_batch,
    sync_from_raw_forms,
)
from tests.integration.helpers.persons import insert_person, insert_person_name_form
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def _fetch_pnf_for(conn, person_id):
    rows = conn.execute(
        text("""
            SELECT name_form, sources FROM person_name_forms
            WHERE person_id = :pid ORDER BY name_form
        """),
        {"pid": person_id},
    ).all()
    return [(r.name_form, list(r.sources)) for r in rows]


class TestFetchPersonsNames:
    def test_includes_excluded(self, sa_sync_conn):
        """Les personnes exclues, pour l'un ou l'autre motif, restent des ancres du matching."""
        active = insert_person(sa_sync_conn, "A", first_name="Jean")
        not_a_person = insert_person(sa_sync_conn, "B", first_name="Jean", exclusion="not_a_person")
        out_of_perimeter = insert_person(
            sa_sync_conn, "C", first_name="Jean", exclusion="out_of_perimeter"
        )

        ids = [r.id for r in fetch_persons_names(sa_sync_conn)]
        assert {active, not_a_person, out_of_perimeter} <= set(ids)

    def test_trims_names(self, sa_sync_conn):
        pid = insert_person(sa_sync_conn, "  Dupond", first_name="Jean  ")
        rows = fetch_persons_names(sa_sync_conn)
        row = next(r for r in rows if r.id == pid)
        assert row.last_name == "Dupond"
        assert row.first_name == "Jean"


class TestSyncFromRawForms:
    def test_inserts_form_from_raw_forms_with_persons_source(self, sa_sync_conn):
        """Une forme `'persons'` poussée en `_raw_forms` apparaît en base après sync, avec `sources = ['persons']`."""
        pid = insert_person(sa_sync_conn, "Dupont", first_name="Jean")

        create_temp_raw_forms_table(sa_sync_conn)
        insert_raw_forms_batch(
            sa_sync_conn,
            [{"name_form": "dupond j", "person_id": pid, "source": "persons"}],
        )
        inserted, updated, deleted = sync_from_raw_forms(sa_sync_conn)
        drop_temp_raw_forms_table(sa_sync_conn)

        assert _fetch_pnf_for(sa_sync_conn, pid) == [("dupond j", ["persons"])]
        assert inserted == 1 and updated == 0 and deleted == 0

    def test_aggregates_sources_across_authorships_and_persons(self, sa_sync_conn):
        """Une forme observée à la fois en `_raw_forms` (source 'persons')
        et en `source_authorships` (source 'hal') aboutit à `sources` mergé."""
        pid = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        sd = insert_source_publication(sa_sync_conn, source_id="h-1")
        insert_signature(
            sa_sync_conn, sd, person_id=pid, author_name_normalized="dupond j", source="hal"
        )

        create_temp_raw_forms_table(sa_sync_conn)
        insert_raw_forms_batch(
            sa_sync_conn,
            [{"name_form": "dupond j", "person_id": pid, "source": "persons"}],
        )
        sync_from_raw_forms(sa_sync_conn)
        drop_temp_raw_forms_table(sa_sync_conn)

        rows = _fetch_pnf_for(sa_sync_conn, pid)
        assert ("dupond j", ["hal", "persons"]) in rows

    def test_deletes_missing_form(self, sa_sync_conn):
        """Une row en base qui n'est plus attendue (ni dans `_raw_forms`
        ni dans `source_authorships`) est supprimée."""
        pid = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        insert_person_name_form(sa_sync_conn, pid, name_form="obsolete", sources=["persons"])

        create_temp_raw_forms_table(sa_sync_conn)
        # _raw_forms vide + aucune source_authorship → l'attendu est vide
        inserted, updated, deleted = sync_from_raw_forms(sa_sync_conn)
        drop_temp_raw_forms_table(sa_sync_conn)

        assert deleted >= 1
        rows = _fetch_pnf_for(sa_sync_conn, pid)
        assert ("obsolete", ["persons"]) not in rows

    def test_updates_sources_when_changed(self, sa_sync_conn):
        """Une row existante dont `sources` diffère de l'attendu est UPDATE,
        pas DELETE/INSERT (et `updated` est incrémenté)."""
        pid = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        sd = insert_source_publication(sa_sync_conn, source_id="h-1")
        insert_signature(
            sa_sync_conn, sd, person_id=pid, author_name_normalized="dupond j", source="openalex"
        )
        # Base : sources = ['hal'] (obsolète vs source_authorships qui dit openalex)
        insert_person_name_form(sa_sync_conn, pid, name_form="dupond j", sources=["hal"])

        create_temp_raw_forms_table(sa_sync_conn)
        inserted, updated, deleted = sync_from_raw_forms(sa_sync_conn)
        drop_temp_raw_forms_table(sa_sync_conn)

        assert updated >= 1
        rows = _fetch_pnf_for(sa_sync_conn, pid)
        assert ("dupond j", ["openalex"]) in rows
