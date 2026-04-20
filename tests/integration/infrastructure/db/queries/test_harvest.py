"""Tests d'intégration pour `infrastructure.db.queries.harvest`."""

import json

from infrastructure.db.queries.harvest import (
    fetch_hal_persons_missing_identifiers,
    fetch_hal_persons_missing_idref,
    fill_source_person_idref_if_null,
    fill_source_person_orcid_if_null,
    update_source_person_idref,
)


def _create_person(db):
    db.execute(
        """
        INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized)
        VALUES ('X', 'Y', 'x', 'y') RETURNING id
        """
    )
    return db.fetchone()["id"]


def _create_sp(
    db,
    *,
    source_id,
    source="hal",
    person_id=None,
    hal_person_id=None,
    idhal=None,
    orcid=None,
    idref=None,
):
    source_ids = {}
    if hal_person_id is not None:
        source_ids["hal_person_id"] = hal_person_id
    if idhal:
        source_ids["idhal"] = idhal
    db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, person_id, source_ids, orcid, idref)
        VALUES (%s, %s, 'Dupond Jean', %s, %s::jsonb, %s, %s)
        RETURNING id
        """,
        (
            source,
            source_id,
            person_id,
            json.dumps(source_ids) if source_ids else None,
            orcid,
            idref,
        ),
    )
    return db.fetchone()["id"]


class TestFetchHalPersonsMissingIdref:
    def test_returns_hal_persons_without_idref(self, db):
        pid = _create_person(db)
        missing = _create_sp(db, source_id="m1", person_id=pid, hal_person_id=42)
        _create_sp(db, source_id="has", person_id=pid, hal_person_id=43, idref="123")
        _create_sp(db, source_id="no-pid", hal_person_id=44)  # sans person_id
        _create_sp(db, source_id="no-halpid", person_id=pid)  # sans hal_person_id

        rows = fetch_hal_persons_missing_idref(db)
        ha_ids = [r["ha_id"] for r in rows]
        assert missing in ha_ids
        # Filtres respectés
        assert all(r["person_id"] is not None for r in rows)
        assert all(r["hal_person_id"] is not None for r in rows)


class TestFetchHalPersonsMissingIdentifiers:
    def test_returns_rows_with_hal_id_and_missing_orcid_or_idref(self, db):
        pid = _create_person(db)
        missing_orcid = _create_sp(db, source_id="o1", person_id=pid, hal_person_id=1, idref="r")
        missing_idref = _create_sp(db, source_id="i1", person_id=pid, hal_person_id=2, orcid="0000")
        complete = _create_sp(
            db, source_id="c1", person_id=pid, hal_person_id=3, orcid="0001", idref="r2"
        )

        rows = fetch_hal_persons_missing_identifiers(db)
        # Le curseur de test est dict_row → rows de dicts
        ids = [r["id"] for r in rows]
        assert missing_orcid in ids
        assert missing_idref in ids
        assert complete not in ids


class TestUpdateSourcePersonIdref:
    def test_overwrites_idref(self, db):
        sp = _create_sp(db, source_id="u1", idref="old")
        update_source_person_idref(db, sp, "new")
        db.execute("SELECT idref FROM source_persons WHERE id = %s", (sp,))
        assert db.fetchone()["idref"] == "new"


class TestFillSourcePersonOrcidIfNull:
    def test_fills_when_null(self, db):
        sp = _create_sp(db, source_id="n1", orcid=None)
        changed = fill_source_person_orcid_if_null(db, sp, "0000-1")
        assert changed is True
        db.execute("SELECT orcid FROM source_persons WHERE id = %s", (sp,))
        assert db.fetchone()["orcid"] == "0000-1"

    def test_noop_when_already_set(self, db):
        sp = _create_sp(db, source_id="n2", orcid="kept")
        changed = fill_source_person_orcid_if_null(db, sp, "new")
        assert changed is False
        db.execute("SELECT orcid FROM source_persons WHERE id = %s", (sp,))
        assert db.fetchone()["orcid"] == "kept"


class TestFillSourcePersonIdrefIfNull:
    def test_fills_when_null(self, db):
        sp = _create_sp(db, source_id="r1", idref=None)
        assert fill_source_person_idref_if_null(db, sp, "R1") is True
        db.execute("SELECT idref FROM source_persons WHERE id = %s", (sp,))
        assert db.fetchone()["idref"] == "R1"

    def test_noop_when_already_set(self, db):
        sp = _create_sp(db, source_id="r2", idref="kept")
        assert fill_source_person_idref_if_null(db, sp, "new") is False
        db.execute("SELECT idref FROM source_persons WHERE id = %s", (sp,))
        assert db.fetchone()["idref"] == "kept"
