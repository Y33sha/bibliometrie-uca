"""Tests d'intégration pour `infrastructure.queries.pipeline.person_name_forms`."""

from sqlalchemy import text

from infrastructure.queries.pipeline.person_name_forms import (
    create_temp_raw_forms_table,
    drop_temp_raw_forms_table,
    fetch_persons_names,
    insert_raw_forms_batch,
    sync_from_raw_forms,
)
from tests.integration.helpers.authorships import upsert_identity


def _create_person(conn, last="Dupont", first="Jean", rejected=False):
    return conn.execute(
        text("""
            INSERT INTO persons
                (last_name, first_name, last_name_normalized, first_name_normalized, rejected)
            VALUES (:last, :first, lower(:last), lower(:first), :rejected)
            RETURNING id
        """),
        {"last": last, "first": first, "rejected": rejected},
    ).scalar_one()


def _create_sd(conn):
    return conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title) "
            "VALUES ('hal', 'h-1', 'X') RETURNING id"
        )
    ).scalar_one()


def _create_sa(
    conn,
    sd,
    *,
    author_position=0,
    person_id=None,
    author_name_normalized=None,
    source="hal",
):
    identity_id = upsert_identity(conn, author_name_normalized=author_name_normalized)
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 person_id, identity_id)
            VALUES (:source, :sd, :pos, :person_id, :iid) RETURNING id
        """),
        {
            "source": source,
            "sd": sd,
            "pos": author_position,
            "person_id": person_id,
            "iid": identity_id,
        },
    ).scalar_one()


def _insert_pnf(conn, name_form, person_id, sources):
    conn.execute(
        text("""
            INSERT INTO person_name_forms (name_form, person_id, sources)
            VALUES (:nf, :pid, :sources)
        """),
        {"nf": name_form, "pid": person_id, "sources": sources},
    )


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
    def test_includes_rejected(self, sa_sync_conn):
        """Les rejected sont conservés pour servir d'ancre de matching
        (entités douteuses, artefacts de parsing) et empêcher la
        re-création en boucle au prochain run pipeline."""
        active = _create_person(sa_sync_conn, last="A")
        rejected = _create_person(sa_sync_conn, last="B", rejected=True)

        rows = fetch_persons_names(sa_sync_conn)
        ids = [r.id for r in rows]
        assert active in ids
        assert rejected in ids

    def test_trims_names(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn, last="  Dupond", first="Jean  ")
        rows = fetch_persons_names(sa_sync_conn)
        row = next(r for r in rows if r.id == pid)
        assert row.last_name == "Dupond"
        assert row.first_name == "Jean"


class TestSyncFromRawForms:
    def test_inserts_form_from_raw_forms_with_persons_source(self, sa_sync_conn):
        """Une forme `'persons'` poussée en `_raw_forms` apparaît en base
        après sync, avec `sources = ['persons']` et normalisée par SQL."""
        pid = _create_person(sa_sync_conn)

        create_temp_raw_forms_table(sa_sync_conn)
        insert_raw_forms_batch(
            sa_sync_conn,
            [{"raw_text": "  DUPOND J  ", "person_id": pid, "source": "persons"}],
        )
        inserted, updated, deleted = sync_from_raw_forms(sa_sync_conn)
        drop_temp_raw_forms_table(sa_sync_conn)

        rows = _fetch_pnf_for(sa_sync_conn, pid)
        assert len(rows) == 1
        nf, sources = rows[0]
        assert "dupond" in nf
        assert sources == ["persons"]
        assert inserted == 1 and updated == 0 and deleted == 0

    def test_aggregates_sources_across_authorships_and_persons(self, sa_sync_conn):
        """Une forme observée à la fois en `_raw_forms` (source 'persons')
        et en `source_authorships` (source 'hal') aboutit à `sources` mergé."""
        pid = _create_person(sa_sync_conn)
        sd = _create_sd(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, person_id=pid, author_name_normalized="dupond j", source="hal")

        create_temp_raw_forms_table(sa_sync_conn)
        insert_raw_forms_batch(
            sa_sync_conn,
            [{"raw_text": "dupond j", "person_id": pid, "source": "persons"}],
        )
        sync_from_raw_forms(sa_sync_conn)
        drop_temp_raw_forms_table(sa_sync_conn)

        rows = _fetch_pnf_for(sa_sync_conn, pid)
        assert ("dupond j", ["hal", "persons"]) in rows

    def test_deletes_missing_form(self, sa_sync_conn):
        """Une row en base qui n'est plus attendue (ni dans `_raw_forms`
        ni dans `source_authorships`) est supprimée."""
        pid = _create_person(sa_sync_conn)
        _insert_pnf(sa_sync_conn, "obsolete", pid, ["persons"])

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
        pid = _create_person(sa_sync_conn)
        sd = _create_sd(sa_sync_conn)
        _create_sa(
            sa_sync_conn,
            sd,
            person_id=pid,
            author_name_normalized="dupond j",
            source="openalex",
        )
        # Base : sources = ['hal'] (obsolète vs source_authorships qui dit openalex)
        _insert_pnf(sa_sync_conn, "dupond j", pid, ["hal"])

        create_temp_raw_forms_table(sa_sync_conn)
        inserted, updated, deleted = sync_from_raw_forms(sa_sync_conn)
        drop_temp_raw_forms_table(sa_sync_conn)

        assert updated >= 1
        rows = _fetch_pnf_for(sa_sync_conn, pid)
        assert ("dupond j", ["openalex"]) in rows
