"""Tests d'intégration pour `infrastructure.db.queries.address_resolution`."""

from infrastructure.db.queries.address_resolution import (
    delete_obsolete_detections,
    fetch_addresses_to_resolve,
    load_name_forms,
    mark_address_resolved,
    reset_all_resolved_at,
    reset_auto_detected,
    unflag_obsolete_detections,
    upsert_detected_structure,
)


def _create_structure(db, code="X"):
    db.execute(
        "INSERT INTO structures (code, name, structure_type) VALUES (%s, 'X', 'labo') RETURNING id",
        (code,),
    )
    return db.fetchone()["id"]


def _create_form(db, struct_id, form_text="uca"):
    db.execute(
        "INSERT INTO structure_name_forms (structure_id, form_text) VALUES (%s, %s) RETURNING id",
        (struct_id, form_text),
    )
    return db.fetchone()["id"]


def _create_address(db, raw_text="X", resolved_at=None):
    if resolved_at is not None:
        db.execute(
            "INSERT INTO addresses (raw_text, normalized_text, resolved_at) VALUES (%s, %s, %s) RETURNING id",
            (raw_text, raw_text, resolved_at),
        )
    else:
        db.execute(
            "INSERT INTO addresses (raw_text, normalized_text) VALUES (%s, %s) RETURNING id",
            (raw_text, raw_text),
        )
    return db.fetchone()["id"]


class TestLoadNameForms:
    def test_returns_all_forms(self, db):
        s = _create_structure(db)
        f = _create_form(db, s, form_text="uca")
        rows = load_name_forms(db)
        assert any(r["id"] == f for r in rows)
        ours = next(r for r in rows if r["id"] == f)
        assert ours["structure_id"] == s
        assert ours["form_text"] == "uca"


class TestResetAutoDetected:
    def test_deletes_matched_links(self, db):
        s = _create_structure(db)
        f = _create_form(db, s)
        addr = _create_address(db)
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
            "VALUES (%s, %s, %s)",
            (addr, s, f),
        )
        count = reset_auto_detected(db)
        assert count >= 1
        db.execute(
            "SELECT 1 FROM address_structures WHERE address_id = %s AND matched_form_id IS NOT NULL",
            (addr,),
        )
        assert db.fetchone() is None

    def test_keeps_manual_links(self, db):
        s = _create_structure(db)
        addr = _create_address(db)
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
            "VALUES (%s, %s, TRUE)",
            (addr, s),
        )
        reset_auto_detected(db)
        db.execute(
            "SELECT 1 FROM address_structures WHERE address_id = %s AND is_confirmed = TRUE",
            (addr,),
        )
        assert db.fetchone() is not None


class TestResetAllResolvedAt:
    def test_nullifies_resolved_at(self, db):
        addr = _create_address(db)
        db.execute("UPDATE addresses SET resolved_at = now() WHERE id = %s", (addr,))
        reset_all_resolved_at(db)
        db.execute("SELECT resolved_at FROM addresses WHERE id = %s", (addr,))
        assert db.fetchone()["resolved_at"] is None


class TestFetchAddressesToResolve:
    def test_incremental_returns_only_unresolved(self, db):
        # Adresse résolue
        db.execute(
            "INSERT INTO addresses (raw_text, normalized_text, resolved_at) "
            "VALUES ('Done', 'done', now()) RETURNING id"
        )
        resolved = db.fetchone()["id"]
        # Adresse non résolue
        todo = _create_address(db, raw_text="Todo")

        rows = fetch_addresses_to_resolve(db, incremental=True)
        ids = [r["id"] for r in rows]
        assert todo in ids
        assert resolved not in ids

    def test_non_incremental_returns_all(self, db):
        a1 = _create_address(db, raw_text="A1")
        a2 = _create_address(db, raw_text="A2")
        rows = fetch_addresses_to_resolve(db, incremental=False)
        ids = [r["id"] for r in rows]
        assert a1 in ids and a2 in ids


class TestDeleteObsoleteDetections:
    def test_keeps_structures_in_kept_list(self, db):
        s1 = _create_structure(db, code="S1")
        s2 = _create_structure(db, code="S2")
        f = _create_form(db, s1)
        addr = _create_address(db)
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
            "VALUES (%s, %s, %s)",
            (addr, s1, f),
        )
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
            "VALUES (%s, %s, %s)",
            (addr, s2, f),
        )

        count = delete_obsolete_detections(db, addr, kept_structure_ids=[s1])
        # Seul le lien vers s2 supprimé
        assert count == 1
        db.execute(
            "SELECT structure_id FROM address_structures WHERE address_id = %s", (addr,)
        )
        remaining = [r["structure_id"] for r in db.fetchall()]
        assert s1 in remaining and s2 not in remaining

    def test_deletes_all_when_kept_empty(self, db):
        s = _create_structure(db)
        f = _create_form(db, s)
        addr = _create_address(db)
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
            "VALUES (%s, %s, %s)",
            (addr, s, f),
        )
        count = delete_obsolete_detections(db, addr, kept_structure_ids=[])
        assert count == 1

    def test_preserves_manually_confirmed_links(self, db):
        s = _create_structure(db)
        f = _create_form(db, s)
        addr = _create_address(db)
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, matched_form_id, is_confirmed) "
            "VALUES (%s, %s, %s, TRUE)",
            (addr, s, f),
        )
        count = delete_obsolete_detections(db, addr, kept_structure_ids=[])
        assert count == 0  # lien manuel non supprimé


class TestUnflagObsoleteDetections:
    def test_clears_matched_form_id_on_confirmed(self, db):
        s1 = _create_structure(db, code="S1")
        s2 = _create_structure(db, code="S2")
        f = _create_form(db, s1)
        addr = _create_address(db)
        db.execute(
            "INSERT INTO address_structures (address_id, structure_id, matched_form_id, is_confirmed) "
            "VALUES (%s, %s, %s, TRUE)",
            (addr, s2, f),
        )

        unflag_obsolete_detections(db, addr, kept_structure_ids=[s1])
        db.execute(
            "SELECT matched_form_id, is_confirmed FROM address_structures "
            "WHERE address_id = %s AND structure_id = %s",
            (addr, s2),
        )
        row = db.fetchone()
        assert row["matched_form_id"] is None
        assert row["is_confirmed"] is True  # is_confirmed préservé


class TestUpsertDetectedStructure:
    def test_inserts_new(self, db):
        s = _create_structure(db)
        f = _create_form(db, s)
        addr = _create_address(db)
        upsert_detected_structure(db, addr, s, f)
        db.execute(
            "SELECT matched_form_id FROM address_structures WHERE address_id = %s AND structure_id = %s",
            (addr, s),
        )
        assert db.fetchone()["matched_form_id"] == f

    def test_updates_existing(self, db):
        s = _create_structure(db)
        f1 = _create_form(db, s, form_text="x1")
        f2 = _create_form(db, s, form_text="x2")
        addr = _create_address(db)
        upsert_detected_structure(db, addr, s, f1)
        upsert_detected_structure(db, addr, s, f2)
        db.execute(
            "SELECT matched_form_id FROM address_structures WHERE address_id = %s AND structure_id = %s",
            (addr, s),
        )
        assert db.fetchone()["matched_form_id"] == f2


class TestMarkAddressResolved:
    def test_sets_resolved_at(self, db):
        addr = _create_address(db)
        mark_address_resolved(db, addr)
        db.execute("SELECT resolved_at FROM addresses WHERE id = %s", (addr,))
        assert db.fetchone()["resolved_at"] is not None
