"""Tests d'intégration pour `infrastructure.db.queries.name_forms`."""

from infrastructure.db.queries.name_forms import (
    create_temp_raw_forms_table,
    delete_name_form,
    drop_temp_raw_forms_table,
    fetch_active_persons_names,
    fetch_existing_name_forms,
    fetch_normalized_forms_from_temp,
    fetch_source_authorship_name_forms,
    insert_name_form_with_merge,
    insert_raw_forms_batch,
    update_name_form,
)


def _create_person(db, last="Dupont", first="Jean", rejected=False):
    db.execute(
        """
        INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized, rejected)
        VALUES (%s, %s, lower(%s), lower(%s), %s)
        RETURNING id
        """,
        (last, first, last, first, rejected),
    )
    return db.fetchone()["id"]


def _create_sd(db):
    db.execute(
        "INSERT INTO source_publications (source, source_id, title) VALUES ('hal', 'h-1', 'X') RETURNING id"
    )
    return db.fetchone()["id"]


def _create_sp(db, source_id="sp-1"):
    db.execute(
        "INSERT INTO source_persons (source, source_id, full_name) VALUES ('hal', %s, 'X') RETURNING id",
        (source_id,),
    )
    return db.fetchone()["id"]


def _create_sa(
    db, sd, sp, person_id=None, author_name_normalized=None, excluded=False, source="hal"
):
    db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             person_id, author_name_normalized, excluded)
        VALUES (%s, %s, %s, 0, %s, %s, %s) RETURNING id
        """,
        (source, sd, sp, person_id, author_name_normalized, excluded),
    )
    return db.fetchone()["id"]


def _insert_name_form(db, name_form, person_ids, sources=None):
    db.execute(
        """
        INSERT INTO person_name_forms (name_form, person_ids, sources)
        VALUES (%s, %s, %s) RETURNING id
        """,
        (name_form, person_ids, sources),
    )
    return db.fetchone()["id"]


class TestFetchActivePersonsNames:
    def test_excludes_rejected(self, db):
        active = _create_person(db, last="A")
        _create_person(db, last="B", rejected=True)

        rows = fetch_active_persons_names(db)
        ids = [r["id"] for r in rows]
        assert active in ids
        assert all(r["last_name"] != "B" for r in rows)

    def test_trims_names(self, db):
        pid = _create_person(db, last="  Dupond", first="Jean  ")
        rows = fetch_active_persons_names(db)
        row = next(r for r in rows if r["id"] == pid)
        assert row["last_name"] == "Dupond"
        assert row["first_name"] == "Jean"


class TestFetchSourceAuthorshipNameForms:
    def test_returns_distinct_rows(self, db):
        pid = _create_person(db)
        sd = _create_sd(db)
        sp = _create_sp(db)
        _create_sa(db, sd, sp, person_id=pid, author_name_normalized="dupond j")

        sp2 = _create_sp(db, source_id="sp-2")
        _create_sa(db, sd, sp2, person_id=pid, author_name_normalized="dupond j")

        rows = fetch_source_authorship_name_forms(db)
        ours = [r for r in rows if r["person_id"] == pid]
        assert len(ours) == 1
        assert ours[0]["name_form"] == "dupond j"
        assert ours[0]["source"] == "hal"

    def test_excludes_excluded_rows(self, db):
        pid = _create_person(db)
        sd = _create_sd(db)
        sp = _create_sp(db)
        _create_sa(db, sd, sp, person_id=pid, author_name_normalized="gone", excluded=True)

        rows = fetch_source_authorship_name_forms(db)
        assert not any(r["name_form"] == "gone" for r in rows)

    def test_excludes_rows_without_person_id_or_name(self, db):
        sd = _create_sd(db)
        sp = _create_sp(db)
        _create_sa(db, sd, sp, person_id=None, author_name_normalized="no-person")
        rows = fetch_source_authorship_name_forms(db)
        assert not any(r["name_form"] == "no-person" for r in rows)


class TestTempRawFormsRoundtrip:
    def test_create_insert_fetch_drop(self, db):
        pid = _create_person(db)

        create_temp_raw_forms_table(db)
        insert_raw_forms_batch(db, [("  DUPOND J  ", pid, "hal"), ("Dupond Jean", pid, "persons")])
        rows = fetch_normalized_forms_from_temp(db)

        assert len(rows) >= 1
        # normalize_name_form abaisse la casse et déroule les accents
        normalized = {r["name_form"] for r in rows}
        assert any("dupond" in n for n in normalized)

        drop_temp_raw_forms_table(db)
        # La table a bien disparu
        db.execute("SELECT to_regclass('pg_temp._raw_forms') AS t")
        assert db.fetchone()["t"] is None


class TestExistingNameFormsCrud:
    def test_fetch_existing(self, db):
        pid = _create_person(db)
        form_id = _insert_name_form(db, "dupond j", [pid], ["hal"])

        rows = fetch_existing_name_forms(db)
        ours = [r for r in rows if r["id"] == form_id]
        assert len(ours) == 1
        assert ours[0]["person_ids"] == [pid]

    def test_update_name_form(self, db):
        pid1 = _create_person(db, last="A")
        pid2 = _create_person(db, last="B")
        form_id = _insert_name_form(db, "ab", [pid1], ["hal"])

        update_name_form(db, form_id, [pid1, pid2], ["hal", "persons"])

        db.execute("SELECT person_ids, sources FROM person_name_forms WHERE id = %s", (form_id,))
        row = db.fetchone()
        assert sorted(row["person_ids"]) == sorted([pid1, pid2])
        assert set(row["sources"]) == {"hal", "persons"}

    def test_insert_name_form_with_merge_conflict_unions(self, db):
        pid1 = _create_person(db, last="A")
        pid2 = _create_person(db, last="B")
        _insert_name_form(db, "nom-x", [pid1], ["hal"])

        insert_name_form_with_merge(db, "nom-x", [pid2], ["openalex"])

        db.execute("SELECT person_ids, sources FROM person_name_forms WHERE name_form = 'nom-x'")
        row = db.fetchone()
        assert sorted(row["person_ids"]) == sorted([pid1, pid2])
        assert set(row["sources"]) == {"hal", "openalex"}

    def test_insert_name_form_with_merge_new(self, db):
        pid = _create_person(db)
        insert_name_form_with_merge(db, "nouveau", [pid], ["hal"])
        db.execute("SELECT person_ids FROM person_name_forms WHERE name_form = 'nouveau'")
        assert db.fetchone()["person_ids"] == [pid]

    def test_delete_name_form(self, db):
        pid = _create_person(db)
        form_id = _insert_name_form(db, "tmp", [pid], ["hal"])
        delete_name_form(db, form_id)
        db.execute("SELECT 1 FROM person_name_forms WHERE id = %s", (form_id,))
        assert db.fetchone() is None
