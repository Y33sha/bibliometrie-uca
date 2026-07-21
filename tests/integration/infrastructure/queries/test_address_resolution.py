"""Tests d'intégration pour `infrastructure.queries.pipeline.affiliations.address_resolution`."""

from sqlalchemy import text

from application.ports.pipeline.affiliations.address_resolution import (
    DetectedStructure,
    KeptPair,
)
from infrastructure.queries.pipeline.affiliations.address_resolution import (
    delete_obsolete_detections_bulk,
    fetch_addresses_chunk,
    load_name_forms,
    unflag_obsolete_detections_bulk,
    upsert_detected_structures_bulk,
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
            "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
            "VALUES (:struct_id, :form_text, char_length(:form_text) <= 6) RETURNING id"
        ),
        {"struct_id": struct_id, "form_text": form_text},
    ).scalar_one()


def _create_address(conn, raw_text="X"):
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


class TestFetchAddressesChunk:
    def test_returns_all_addresses(self, sa_sync_conn):
        a1 = _create_address(sa_sync_conn, raw_text="A1")
        a2 = _create_address(sa_sync_conn, raw_text="A2")
        rows = fetch_addresses_chunk(sa_sync_conn, after_id=0, limit=1000)
        ids = [addr_id for addr_id, _ in rows]
        assert a1 in ids and a2 in ids

    def test_keyset_after_id_and_limit(self, sa_sync_conn):
        """`after_id` exclut les ids <= seuil ; `limit` borne la tranche, triée par id."""
        a1 = _create_address(sa_sync_conn, raw_text="A1")
        a2 = _create_address(sa_sync_conn, raw_text="A2")
        a3 = _create_address(sa_sync_conn, raw_text="A3")
        rows = fetch_addresses_chunk(sa_sync_conn, after_id=a1, limit=1)
        ids = [addr_id for addr_id, _ in rows]
        assert ids == [a2]  # a1 exclu (id <= after_id), a3 hors limite
        assert a3 > a2  # ordre par id garanti

    def test_returns_normalized_text_tuples(self, sa_sync_conn):
        addr_id = _create_address(sa_sync_conn, raw_text="Some address")
        rows = fetch_addresses_chunk(sa_sync_conn, after_id=0, limit=1000)
        assert all(isinstance(r, tuple) and len(r) == 2 for r in rows)
        row = next(r for r in rows if r[0] == addr_id)
        assert isinstance(row[0], int)
        assert row[1] == "Some address"


class TestDeleteObsoleteDetectionsBulk:
    def test_keeps_pairs_in_kept_list(self, sa_sync_conn):
        s1 = _create_structure(sa_sync_conn, code="S1")
        s2 = _create_structure(sa_sync_conn, code="S2")
        f = _create_form(sa_sync_conn, s1)
        addr = _create_address(sa_sync_conn)
        for struct in (s1, s2):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
                    "VALUES (:addr, :struct, :form)"
                ),
                {"addr": addr, "struct": struct, "form": f},
            )

        count = delete_obsolete_detections_bulk(
            sa_sync_conn, [addr], kept_pairs=[KeptPair(addr, s1)]
        )
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
        count = delete_obsolete_detections_bulk(sa_sync_conn, [addr], kept_pairs=[])
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
        count = delete_obsolete_detections_bulk(sa_sync_conn, [addr], kept_pairs=[])
        assert count == 0  # lien manuel non supprimé

    def test_pair_scoped_not_structure_scoped(self, sa_sync_conn):
        """Une même structure gardée pour une adresse n'épargne pas une autre adresse."""
        s = _create_structure(sa_sync_conn)
        f = _create_form(sa_sync_conn, s)
        addr1 = _create_address(sa_sync_conn, raw_text="A1")
        addr2 = _create_address(sa_sync_conn, raw_text="A2")
        for addr in (addr1, addr2):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO address_structures (address_id, structure_id, matched_form_id) "
                    "VALUES (:addr, :struct, :form)"
                ),
                {"addr": addr, "struct": s, "form": f},
            )
        # On garde (addr1, s) ; (addr2, s) devient obsolète bien que même structure.
        count = delete_obsolete_detections_bulk(
            sa_sync_conn, [addr1, addr2], kept_pairs=[KeptPair(addr1, s)]
        )
        assert count == 1
        remaining = (
            sa_sync_conn.execute(
                text("SELECT address_id FROM address_structures WHERE structure_id = :s"),
                {"s": s},
            )
            .scalars()
            .all()
        )
        assert addr1 in remaining and addr2 not in remaining


class TestUnflagObsoleteDetectionsBulk:
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

        unflag_obsolete_detections_bulk(sa_sync_conn, [addr], kept_pairs=[KeptPair(addr, s1)])
        row = sa_sync_conn.execute(
            text(
                "SELECT matched_form_id, is_confirmed FROM address_structures "
                "WHERE address_id = :addr AND structure_id = :struct"
            ),
            {"addr": addr, "struct": s2},
        ).one()
        assert row.matched_form_id is None
        assert row.is_confirmed is True  # is_confirmed préservé


class TestUpsertDetectedStructuresBulk:
    def test_inserts_new(self, sa_sync_conn):
        s = _create_structure(sa_sync_conn)
        f = _create_form(sa_sync_conn, s)
        addr = _create_address(sa_sync_conn)
        upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f)])
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
        upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f1)])
        upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f2)])
        result = sa_sync_conn.execute(
            text(
                "SELECT matched_form_id FROM address_structures "
                "WHERE address_id = :addr AND structure_id = :struct"
            ),
            {"addr": addr, "struct": s},
        ).scalar_one()
        assert result == f2

    def test_inserts_many_in_one_call(self, sa_sync_conn):
        s1 = _create_structure(sa_sync_conn, code="S1")
        s2 = _create_structure(sa_sync_conn, code="S2")
        f1 = _create_form(sa_sync_conn, s1)
        f2 = _create_form(sa_sync_conn, s2, form_text="y")
        addr = _create_address(sa_sync_conn)
        upsert_detected_structures_bulk(
            sa_sync_conn, [DetectedStructure(addr, s1, f1), DetectedStructure(addr, s2, f2)]
        )
        count = sa_sync_conn.execute(
            text("SELECT count(*) FROM address_structures WHERE address_id = :addr"),
            {"addr": addr},
        ).scalar_one()
        assert count == 2

    def test_idempotent_skips_noop_update(self, sa_sync_conn):
        """Réinsérer une détection identique n'écrit pas de nouvelle version (xmax inchangé)."""
        s = _create_structure(sa_sync_conn)
        f = _create_form(sa_sync_conn, s)
        addr = _create_address(sa_sync_conn)
        upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f)])
        xmin_before = sa_sync_conn.execute(
            text("SELECT xmin FROM address_structures WHERE address_id = :a AND structure_id = :s"),
            {"a": addr, "s": s},
        ).scalar_one()
        # Même détection : l'ON CONFLICT ... WHERE IS DISTINCT FROM ne réécrit rien.
        upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f)])
        xmin_after = sa_sync_conn.execute(
            text("SELECT xmin FROM address_structures WHERE address_id = :a AND structure_id = :s"),
            {"a": addr, "s": s},
        ).scalar_one()
        assert xmin_before == xmin_after  # pas de nouvelle version de ligne
