"""Tests d'intégration pour `infrastructure.queries.address_resolution`."""

from sqlalchemy import text

from infrastructure.queries.address_resolution import (
    delete_obsolete_detections,
    fetch_addresses_to_resolve,
    load_name_forms,
    mark_address_resolved,
    reset_all_resolved_at,
    reset_auto_detected,
    unflag_obsolete_detections,
    upsert_detected_structure,
)


def _create_structure(conn, code="X"):
    return conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:code, 'X', 'labo') RETURNING id"
        ),
        {"code": code},
    ).scalar_one()


def _create_form(conn, struct_id, form_text="uca"):
    return conn.execute(
        text(
            "INSERT INTO structure_name_forms (structure_id, form_text) "
            "VALUES (:struct_id, :form_text) RETURNING id"
        ),
        {"struct_id": struct_id, "form_text": form_text},
    ).scalar_one()


def _create_address(conn, raw_text="X", resolved_at=None):
    if resolved_at is not None:
        return conn.execute(
            text(
                "INSERT INTO addresses (raw_text, normalized_text, resolved_at) "
                "VALUES (:raw, :norm, :resolved) RETURNING id"
            ),
            {"raw": raw_text, "norm": raw_text, "resolved": resolved_at},
        ).scalar_one()
    return conn.execute(
        text("INSERT INTO addresses (raw_text, normalized_text) VALUES (:raw, :norm) RETURNING id"),
        {"raw": raw_text, "norm": raw_text},
    ).scalar_one()


class TestLoadNameForms:
    def test_returns_all_forms(self, sa_sync_conn):
        s = _create_structure(sa_sync_conn)
        f = _create_form(sa_sync_conn, s, form_text="uca")
        rows = load_name_forms(sa_sync_conn)
        assert any(r.id == f for r in rows)
        ours = next(r for r in rows if r.id == f)
        assert ours.structure_id == s
        assert ours.form_text == "uca"


class TestResetAutoDetected:
    def test_deletes_matched_links(self, sa_sync_conn):
        s = _create_structure(sa_sync_conn)
        f = _create_form(sa_sync_conn, s)
        addr = _create_address(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
                "VALUES (:addr, :struct, :form)"
            ),
            {"addr": addr, "struct": s, "form": f},
        )
        count = reset_auto_detected(sa_sync_conn)
        assert count >= 1
        result = sa_sync_conn.execute(
            text(
                "SELECT 1 FROM address_structures "
                "WHERE address_id = :addr AND matched_form_id IS NOT NULL"
            ),
            {"addr": addr},
        ).first()
        assert result is None

    def test_keeps_manual_links(self, sa_sync_conn):
        s = _create_structure(sa_sync_conn)
        addr = _create_address(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
                "VALUES (:addr, :struct, TRUE)"
            ),
            {"addr": addr, "struct": s},
        )
        reset_auto_detected(sa_sync_conn)
        result = sa_sync_conn.execute(
            text(
                "SELECT 1 FROM address_structures WHERE address_id = :addr AND is_confirmed = TRUE"
            ),
            {"addr": addr},
        ).first()
        assert result is not None


class TestResetAllResolvedAt:
    def test_nullifies_resolved_at(self, sa_sync_conn):
        addr = _create_address(sa_sync_conn)
        sa_sync_conn.execute(
            text("UPDATE addresses SET resolved_at = now() WHERE id = :addr"),
            {"addr": addr},
        )
        reset_all_resolved_at(sa_sync_conn)
        result = sa_sync_conn.execute(
            text("SELECT resolved_at FROM addresses WHERE id = :addr"),
            {"addr": addr},
        ).scalar_one()
        assert result is None


class TestFetchAddressesToResolve:
    def test_incremental_returns_only_unresolved(self, sa_sync_conn):
        # Adresse résolue
        resolved = sa_sync_conn.execute(
            text(
                "INSERT INTO addresses (raw_text, normalized_text, resolved_at) "
                "VALUES ('Done', 'done', now()) RETURNING id"
            )
        ).scalar_one()
        # Adresse non résolue
        todo = _create_address(sa_sync_conn, raw_text="Todo")

        rows = fetch_addresses_to_resolve(sa_sync_conn, incremental=True)
        ids = [addr_id for addr_id, _ in rows]
        assert todo in ids
        assert resolved not in ids

    def test_non_incremental_returns_all(self, sa_sync_conn):
        a1 = _create_address(sa_sync_conn, raw_text="A1")
        a2 = _create_address(sa_sync_conn, raw_text="A2")
        rows = fetch_addresses_to_resolve(sa_sync_conn, incremental=False)
        ids = [addr_id for addr_id, _ in rows]
        assert a1 in ids and a2 in ids

    def test_returns_tuples(self, sa_sync_conn):
        """La signature déclare `list[tuple[int, str]]` pour faciliter
        l'unpack côté caller."""
        addr_id = _create_address(sa_sync_conn, raw_text="Some address")
        rows = fetch_addresses_to_resolve(sa_sync_conn, incremental=False)
        assert all(isinstance(r, tuple) and len(r) == 2 for r in rows)
        row = next(r for r in rows if r[0] == addr_id)
        assert isinstance(row[0], int)
        assert row[1] == "Some address"


class TestDeleteObsoleteDetections:
    def test_keeps_structures_in_kept_list(self, sa_sync_conn):
        s1 = _create_structure(sa_sync_conn, code="S1")
        s2 = _create_structure(sa_sync_conn, code="S2")
        f = _create_form(sa_sync_conn, s1)
        addr = _create_address(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
                "VALUES (:addr, :struct, :form)"
            ),
            {"addr": addr, "struct": s1, "form": f},
        )
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
                "VALUES (:addr, :struct, :form)"
            ),
            {"addr": addr, "struct": s2, "form": f},
        )

        count = delete_obsolete_detections(sa_sync_conn, addr, kept_structure_ids=[s1])
        assert count == 1
        rows = sa_sync_conn.execute(
            text("SELECT structure_id FROM address_structures WHERE address_id = :addr"),
            {"addr": addr},
        ).all()
        remaining = [r.structure_id for r in rows]
        assert s1 in remaining and s2 not in remaining

    def test_deletes_all_when_kept_empty(self, sa_sync_conn):
        s = _create_structure(sa_sync_conn)
        f = _create_form(sa_sync_conn, s)
        addr = _create_address(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
                "VALUES (:addr, :struct, :form)"
            ),
            {"addr": addr, "struct": s, "form": f},
        )
        count = delete_obsolete_detections(sa_sync_conn, addr, kept_structure_ids=[])
        assert count == 1

    def test_preserves_manually_confirmed_links(self, sa_sync_conn):
        s = _create_structure(sa_sync_conn)
        f = _create_form(sa_sync_conn, s)
        addr = _create_address(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures "
                "(address_id, structure_id, matched_form_id, is_confirmed) "
                "VALUES (:addr, :struct, :form, TRUE)"
            ),
            {"addr": addr, "struct": s, "form": f},
        )
        count = delete_obsolete_detections(sa_sync_conn, addr, kept_structure_ids=[])
        assert count == 0  # lien manuel non supprimé


class TestUnflagObsoleteDetections:
    def test_clears_matched_form_id_on_confirmed(self, sa_sync_conn):
        s1 = _create_structure(sa_sync_conn, code="S1")
        s2 = _create_structure(sa_sync_conn, code="S2")
        f = _create_form(sa_sync_conn, s1)
        addr = _create_address(sa_sync_conn)
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures "
                "(address_id, structure_id, matched_form_id, is_confirmed) "
                "VALUES (:addr, :struct, :form, TRUE)"
            ),
            {"addr": addr, "struct": s2, "form": f},
        )

        unflag_obsolete_detections(sa_sync_conn, addr, kept_structure_ids=[s1])
        row = sa_sync_conn.execute(
            text(
                "SELECT matched_form_id, is_confirmed FROM address_structures "
                "WHERE address_id = :addr AND structure_id = :struct"
            ),
            {"addr": addr, "struct": s2},
        ).one()
        assert row.matched_form_id is None
        assert row.is_confirmed is True  # is_confirmed préservé


class TestUpsertDetectedStructure:
    def test_inserts_new(self, sa_sync_conn):
        s = _create_structure(sa_sync_conn)
        f = _create_form(sa_sync_conn, s)
        addr = _create_address(sa_sync_conn)
        upsert_detected_structure(sa_sync_conn, addr, s, f)
        result = sa_sync_conn.execute(
            text(
                "SELECT matched_form_id FROM address_structures "
                "WHERE address_id = :addr AND structure_id = :struct"
            ),
            {"addr": addr, "struct": s},
        ).scalar_one()
        assert result == f

    def test_updates_existing(self, sa_sync_conn):
        s = _create_structure(sa_sync_conn)
        f1 = _create_form(sa_sync_conn, s, form_text="x1")
        f2 = _create_form(sa_sync_conn, s, form_text="x2")
        addr = _create_address(sa_sync_conn)
        upsert_detected_structure(sa_sync_conn, addr, s, f1)
        upsert_detected_structure(sa_sync_conn, addr, s, f2)
        result = sa_sync_conn.execute(
            text(
                "SELECT matched_form_id FROM address_structures "
                "WHERE address_id = :addr AND structure_id = :struct"
            ),
            {"addr": addr, "struct": s},
        ).scalar_one()
        assert result == f2


class TestMarkAddressResolved:
    def test_sets_resolved_at(self, sa_sync_conn):
        addr = _create_address(sa_sync_conn)
        mark_address_resolved(sa_sync_conn, addr)
        result = sa_sync_conn.execute(
            text("SELECT resolved_at FROM addresses WHERE id = :addr"),
            {"addr": addr},
        ).scalar_one()
        assert result is not None
