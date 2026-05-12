"""Tests d'intégration pour `infrastructure.db.queries.name_forms`."""

from sqlalchemy import text

from infrastructure.db.queries.name_forms import (
    create_temp_raw_forms_table,
    delete_name_form,
    drop_temp_raw_forms_table,
    fetch_existing_name_forms,
    fetch_normalized_forms_from_temp,
    fetch_persons_names,
    fetch_source_authorship_name_forms,
    insert_name_form_with_merge,
    insert_raw_forms_batch,
    update_name_form,
)


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
    excluded=False,
    source="hal",
):
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position,
                 person_id, author_name_normalized, excluded)
            VALUES (:source, :sd, :pos, :person_id, :anf, :excluded) RETURNING id
        """),
        {
            "source": source,
            "sd": sd,
            "pos": author_position,
            "person_id": person_id,
            "anf": author_name_normalized,
            "excluded": excluded,
        },
    ).scalar_one()


def _insert_name_form(conn, name_form, person_ids, sources=None):
    return conn.execute(
        text("""
            INSERT INTO person_name_forms (name_form, person_ids, sources)
            VALUES (:name_form, :person_ids, :sources) RETURNING id
        """),
        {"name_form": name_form, "person_ids": person_ids, "sources": sources},
    ).scalar_one()


class TestFetchPersonsNames:
    def test_includes_rejected(self, sa_sync_conn):
        """Les rejected sont conservés pour servir d'ancre de matching
        (entités douteuses, artefacts de parsing) et empêcher la
        re-création en boucle au prochain run pipeline."""
        active = _create_person(sa_sync_conn, last="A")
        rejected = _create_person(sa_sync_conn, last="B", rejected=True)

        rows = fetch_persons_names(sa_sync_conn)
        ids = [r["id"] for r in rows]
        assert active in ids
        assert rejected in ids

    def test_trims_names(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn, last="  Dupond", first="Jean  ")
        rows = fetch_persons_names(sa_sync_conn)
        row = next(r for r in rows if r["id"] == pid)
        assert row["last_name"] == "Dupond"
        assert row["first_name"] == "Jean"


class TestFetchSourceAuthorshipNameForms:
    def test_returns_distinct_rows(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
        sd = _create_sd(sa_sync_conn)
        _create_sa(
            sa_sync_conn, sd, author_position=0, person_id=pid, author_name_normalized="dupond j"
        )
        _create_sa(
            sa_sync_conn, sd, author_position=1, person_id=pid, author_name_normalized="dupond j"
        )

        rows = fetch_source_authorship_name_forms(sa_sync_conn)
        ours = [r for r in rows if r["person_id"] == pid]
        assert len(ours) == 1
        assert ours[0]["name_form"] == "dupond j"
        assert ours[0]["source"] == "hal"

    def test_excludes_excluded_rows(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
        sd = _create_sd(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, person_id=pid, author_name_normalized="gone", excluded=True)

        rows = fetch_source_authorship_name_forms(sa_sync_conn)
        assert not any(r["name_form"] == "gone" for r in rows)

    def test_excludes_rows_without_person_id_or_name(self, sa_sync_conn):
        sd = _create_sd(sa_sync_conn)
        _create_sa(sa_sync_conn, sd, person_id=None, author_name_normalized="no-person")
        rows = fetch_source_authorship_name_forms(sa_sync_conn)
        assert not any(r["name_form"] == "no-person" for r in rows)


class TestTempRawFormsRoundtrip:
    def test_create_insert_fetch_drop(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)

        create_temp_raw_forms_table(sa_sync_conn)
        insert_raw_forms_batch(
            sa_sync_conn,
            [
                {"raw_text": "  DUPOND J  ", "person_id": pid, "source": "hal"},
                {"raw_text": "Dupond Jean", "person_id": pid, "source": "persons"},
            ],
        )
        rows = fetch_normalized_forms_from_temp(sa_sync_conn)

        assert len(rows) >= 1
        # normalize_name_form abaisse la casse et déroule les accents
        normalized = {r["name_form"] for r in rows}
        assert any("dupond" in n for n in normalized)

        drop_temp_raw_forms_table(sa_sync_conn)
        # La table a bien disparu
        result = sa_sync_conn.execute(
            text("SELECT to_regclass('pg_temp._raw_forms') AS t")
        ).scalar_one()
        assert result is None


class TestExistingNameFormsCrud:
    def test_fetch_existing(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
        form_id = _insert_name_form(sa_sync_conn, "dupond j", [pid], ["hal"])

        rows = fetch_existing_name_forms(sa_sync_conn)
        ours = [r for r in rows if r["id"] == form_id]
        assert len(ours) == 1
        assert ours[0]["person_ids"] == [pid]

    def test_update_name_form(self, sa_sync_conn):
        pid1 = _create_person(sa_sync_conn, last="A")
        pid2 = _create_person(sa_sync_conn, last="B")
        form_id = _insert_name_form(sa_sync_conn, "ab", [pid1], ["hal"])

        update_name_form(sa_sync_conn, form_id, [pid1, pid2], ["hal", "persons"])

        row = sa_sync_conn.execute(
            text("SELECT person_ids, sources FROM person_name_forms WHERE id = :id"),
            {"id": form_id},
        ).one()
        assert sorted(row.person_ids) == sorted([pid1, pid2])
        assert set(row.sources) == {"hal", "persons"}

    def test_insert_name_form_with_merge_conflict_unions(self, sa_sync_conn):
        pid1 = _create_person(sa_sync_conn, last="A")
        pid2 = _create_person(sa_sync_conn, last="B")
        _insert_name_form(sa_sync_conn, "nom-x", [pid1], ["hal"])

        insert_name_form_with_merge(sa_sync_conn, "nom-x", [pid2], ["openalex"])

        row = sa_sync_conn.execute(
            text("SELECT person_ids, sources FROM person_name_forms WHERE name_form = 'nom-x'")
        ).one()
        assert sorted(row.person_ids) == sorted([pid1, pid2])
        assert set(row.sources) == {"hal", "openalex"}

    def test_insert_name_form_with_merge_new(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
        insert_name_form_with_merge(sa_sync_conn, "nouveau", [pid], ["hal"])
        result = sa_sync_conn.execute(
            text("SELECT person_ids FROM person_name_forms WHERE name_form = 'nouveau'")
        ).scalar_one()
        assert result == [pid]

    def test_delete_name_form(self, sa_sync_conn):
        pid = _create_person(sa_sync_conn)
        form_id = _insert_name_form(sa_sync_conn, "tmp", [pid], ["hal"])
        delete_name_form(sa_sync_conn, form_id)
        result = sa_sync_conn.execute(
            text("SELECT 1 FROM person_name_forms WHERE id = :id"), {"id": form_id}
        ).first()
        assert result is None
