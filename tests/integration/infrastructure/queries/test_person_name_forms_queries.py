"""Tests d'intégration des requêtes de `pipeline.transformation.persons.populate_person_name_forms`."""

from sqlalchemy import text

from pipeline.transformation.persons.populate_person_name_forms import (
    create_temp_raw_forms_table,
    drop_temp_raw_forms_table,
    fetch_persons_names,
    insert_raw_forms_batch,
    sync_from_raw_forms,
)
from tests.integration.helpers.alignment import insert_person_contribution
from tests.integration.helpers.persons import insert_person, insert_person_name_form
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _fetch_pnf_for(conn, person_id):
    rows = conn.execute(
        text("""
            SELECT name_form, sources FROM person_name_forms
            WHERE person_id = :pid ORDER BY name_form
        """),
        {"pid": person_id},
    ).all()
    return [(r.name_form, list(r.sources)) for r in rows]


def _source_contribution(conn, name_form, source):
    """Contribution source de forme `name_form` venue de `source`."""
    source_record = insert_source_record(
        conn, insert_publication(conn, "t"), source=source, source_id=f"{source}-1"
    )
    return insert_source_contribution(
        conn, source_record, source=source, author_name_normalized=name_form
    )


def _sync(conn, raw_forms=()):
    create_temp_raw_forms_table(conn)
    insert_raw_forms_batch(conn, list(raw_forms))
    counts = sync_from_raw_forms(conn)
    drop_temp_raw_forms_table(conn)
    return counts


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

        inserted, updated, deleted = _sync(
            sa_sync_conn, [{"name_form": "dupond j", "person_id": pid, "source": "persons"}]
        )

        assert _fetch_pnf_for(sa_sync_conn, pid) == [("dupond j", ["persons"])]
        assert inserted == 1 and updated == 0 and deleted == 0

    def test_aggregates_sources_across_aligned_source_contributions_and_persons(self, sa_sync_conn):
        """Une forme présente en `_raw_forms` (source 'persons') et présente dans une contribution source HAL d'une contribution de la personne réunit les deux sources."""
        pid = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        insert_person_contribution(
            sa_sync_conn, _source_contribution(sa_sync_conn, "dupond j", "hal"), person_id=pid
        )

        _sync(sa_sync_conn, [{"name_form": "dupond j", "person_id": pid, "source": "persons"}])

        assert ("dupond j", ["hal", "persons"]) in _fetch_pnf_for(sa_sync_conn, pid)

    def test_deletes_missing_form(self, sa_sync_conn):
        """Une forme en base absente de l'état attendu (ni dans `_raw_forms`, ni dans une contribution source des contributions de la personne) est supprimée."""
        pid = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        insert_person_name_form(sa_sync_conn, pid, name_form="obsolete", sources=["persons"])

        inserted, updated, deleted = _sync(sa_sync_conn)

        assert deleted >= 1
        assert ("obsolete", ["persons"]) not in _fetch_pnf_for(sa_sync_conn, pid)

    def test_updates_sources_when_changed(self, sa_sync_conn):
        """Une forme en base dont `sources` diffère de l'attendu est mise à jour, sans suppression ni insertion."""
        pid = insert_person(sa_sync_conn, "Dupont", first_name="Jean")
        insert_person_contribution(
            sa_sync_conn, _source_contribution(sa_sync_conn, "dupond j", "openalex"), person_id=pid
        )
        # Sources en base : ['hal'], alors que la contribution source de la contribution vient d'OpenAlex.
        insert_person_name_form(sa_sync_conn, pid, name_form="dupond j", sources=["hal"])

        inserted, updated, deleted = _sync(sa_sync_conn)

        assert updated >= 1
        assert ("dupond j", ["openalex"]) in _fetch_pnf_for(sa_sync_conn, pid)
