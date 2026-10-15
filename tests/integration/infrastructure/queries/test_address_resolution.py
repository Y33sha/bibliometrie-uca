"""Tests d'intégration pour `pipeline.transformation.structures.address_resolution`."""

from functools import partial

from sqlalchemy import text

from pipeline.transformation.structures.address_resolution import (
    AddressResolutionQueries,
    DetectedStructure,
    KeptPair,
)
from tests.integration.helpers.addresses import insert_address, insert_address_structure
from tests.integration.helpers.structures import insert_structure, insert_structure_name_form

# Forme de nom « uca ».
_uca_form = partial(insert_structure_name_form, form_text="uca")

_Q = AddressResolutionQueries()


class TestLoadNameForms:
    def test_returns_all_forms(self, sa_sync_conn):
        s = insert_structure(sa_sync_conn, name="X")
        f = _uca_form(sa_sync_conn, s)
        rows = _Q.load_name_forms(sa_sync_conn)
        assert any(r.id == f for r in rows)
        ours = next(r for r in rows if r.id == f)
        assert ours.structure_id == s
        assert ours.form_text == "uca"


class TestCountAddresses:
    def test_le_compte_suit_les_adresses_creees(self, sa_sync_conn):
        avant = _Q.count_addresses(sa_sync_conn)
        insert_address(sa_sync_conn, "A1", normalized_text="A1")
        insert_address(sa_sync_conn, "A2", normalized_text="A2")
        assert _Q.count_addresses(sa_sync_conn) == avant + 2


class TestFetchAddressesChunk:
    def test_returns_all_addresses(self, sa_sync_conn):
        a1 = insert_address(sa_sync_conn, "A1", normalized_text="A1")
        a2 = insert_address(sa_sync_conn, "A2", normalized_text="A2")
        rows = _Q.fetch_addresses_chunk(sa_sync_conn, after_id=0, limit=1000)
        ids = [addr_id for addr_id, _ in rows]
        assert a1 in ids and a2 in ids

    def test_keyset_after_id_and_limit(self, sa_sync_conn):
        """`after_id` exclut les ids <= seuil ; `limit` borne la tranche, triée par id."""
        a1 = insert_address(sa_sync_conn, "A1", normalized_text="A1")
        a2 = insert_address(sa_sync_conn, "A2", normalized_text="A2")
        a3 = insert_address(sa_sync_conn, "A3", normalized_text="A3")
        rows = _Q.fetch_addresses_chunk(sa_sync_conn, after_id=a1, limit=1)
        ids = [addr_id for addr_id, _ in rows]
        assert ids == [a2]  # a1 exclu (id <= after_id), a3 hors limite
        assert a3 > a2  # ordre par id garanti

    def test_returns_normalized_text_tuples(self, sa_sync_conn):
        addr_id = insert_address(sa_sync_conn, "Some address", normalized_text="Some address")
        rows = _Q.fetch_addresses_chunk(sa_sync_conn, after_id=0, limit=1000)
        assert all(isinstance(r, tuple) and len(r) == 2 for r in rows)
        row = next(r for r in rows if r[0] == addr_id)
        assert isinstance(row[0], int)
        assert row[1] == "Some address"


class TestDeleteObsoleteDetectionsBulk:
    def test_keeps_pairs_in_kept_list(self, sa_sync_conn):
        s1 = insert_structure(sa_sync_conn, "S1", name="X")
        s2 = insert_structure(sa_sync_conn, "S2", name="X")
        f = _uca_form(sa_sync_conn, s1)
        addr = insert_address(sa_sync_conn, normalized_text="X")
        for struct in (s1, s2):
            insert_address_structure(sa_sync_conn, addr, structure_id=struct, matched_form_id=f)

        count = _Q.delete_obsolete_detections_bulk(
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
        s = insert_structure(sa_sync_conn, name="X")
        f = _uca_form(sa_sync_conn, s)
        addr = insert_address(sa_sync_conn, normalized_text="X")
        insert_address_structure(sa_sync_conn, addr, structure_id=s, matched_form_id=f)
        count = _Q.delete_obsolete_detections_bulk(sa_sync_conn, [addr], kept_pairs=[])
        assert count == 1

    def test_preserves_manually_confirmed_links(self, sa_sync_conn):
        s = insert_structure(sa_sync_conn, name="X")
        f = _uca_form(sa_sync_conn, s)
        addr = insert_address(sa_sync_conn, normalized_text="X")
        insert_address_structure(
            sa_sync_conn, addr, structure_id=s, matched_form_id=f, is_confirmed=True
        )
        count = _Q.delete_obsolete_detections_bulk(sa_sync_conn, [addr], kept_pairs=[])
        assert count == 0  # lien manuel non supprimé

    def test_deletes_unconfirmed_link_whose_form_was_deleted(self, sa_sync_conn):
        """La suppression d'une forme vide `matched_form_id` : le lien, non confirmé et plus détecté, est supprimé."""
        s = insert_structure(sa_sync_conn, name="X")
        f = _uca_form(sa_sync_conn, s)
        addr = insert_address(sa_sync_conn, normalized_text="X")
        insert_address_structure(sa_sync_conn, addr, structure_id=s, matched_form_id=f)
        sa_sync_conn.execute(text("DELETE FROM structure_name_forms WHERE id = :f"), {"f": f})

        count = _Q.delete_obsolete_detections_bulk(sa_sync_conn, [addr], kept_pairs=[])

        assert count == 1

    def test_pair_scoped_not_structure_scoped(self, sa_sync_conn):
        """Une même structure gardée pour une adresse n'épargne pas une autre adresse."""
        s = insert_structure(sa_sync_conn, name="X")
        f = _uca_form(sa_sync_conn, s)
        addr1 = insert_address(sa_sync_conn, "A1", normalized_text="A1")
        addr2 = insert_address(sa_sync_conn, "A2", normalized_text="A2")
        for addr in (addr1, addr2):
            insert_address_structure(sa_sync_conn, addr, structure_id=s, matched_form_id=f)
        # On garde (addr1, s) ; (addr2, s) devient obsolète bien que même structure.
        count = _Q.delete_obsolete_detections_bulk(
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
        s1 = insert_structure(sa_sync_conn, "S1", name="X")
        s2 = insert_structure(sa_sync_conn, "S2", name="X")
        f = _uca_form(sa_sync_conn, s1)
        addr = insert_address(sa_sync_conn, normalized_text="X")
        insert_address_structure(
            sa_sync_conn, addr, structure_id=s2, matched_form_id=f, is_confirmed=True
        )

        _Q.unflag_obsolete_detections_bulk(sa_sync_conn, [addr], kept_pairs=[KeptPair(addr, s1)])
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
        s = insert_structure(sa_sync_conn, name="X")
        f = _uca_form(sa_sync_conn, s)
        addr = insert_address(sa_sync_conn, normalized_text="X")
        _Q.upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f)])
        result = sa_sync_conn.execute(
            text(
                "SELECT matched_form_id FROM address_structures "
                "WHERE address_id = :addr AND structure_id = :struct"
            ),
            {"addr": addr, "struct": s},
        ).scalar_one()
        assert result == f

    def test_updates_existing(self, sa_sync_conn):
        s = insert_structure(sa_sync_conn, name="X")
        f1 = insert_structure_name_form(sa_sync_conn, s, form_text="x1")
        f2 = insert_structure_name_form(sa_sync_conn, s, form_text="x2")
        addr = insert_address(sa_sync_conn, normalized_text="X")
        _Q.upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f1)])
        _Q.upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f2)])
        result = sa_sync_conn.execute(
            text(
                "SELECT matched_form_id FROM address_structures "
                "WHERE address_id = :addr AND structure_id = :struct"
            ),
            {"addr": addr, "struct": s},
        ).scalar_one()
        assert result == f2

    def test_inserts_many_in_one_call(self, sa_sync_conn):
        s1 = insert_structure(sa_sync_conn, "S1", name="X")
        s2 = insert_structure(sa_sync_conn, "S2", name="X")
        f1 = _uca_form(sa_sync_conn, s1)
        f2 = insert_structure_name_form(sa_sync_conn, s2, form_text="y")
        addr = insert_address(sa_sync_conn, normalized_text="X")
        _Q.upsert_detected_structures_bulk(
            sa_sync_conn, [DetectedStructure(addr, s1, f1), DetectedStructure(addr, s2, f2)]
        )
        count = sa_sync_conn.execute(
            text("SELECT count(*) FROM address_structures WHERE address_id = :addr"),
            {"addr": addr},
        ).scalar_one()
        assert count == 2

    def test_idempotent_skips_noop_update(self, sa_sync_conn):
        """Réinsérer une détection identique n'écrit pas de nouvelle version (xmax inchangé)."""
        s = insert_structure(sa_sync_conn, name="X")
        f = _uca_form(sa_sync_conn, s)
        addr = insert_address(sa_sync_conn, normalized_text="X")
        _Q.upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f)])
        xmin_before = sa_sync_conn.execute(
            text("SELECT xmin FROM address_structures WHERE address_id = :a AND structure_id = :s"),
            {"a": addr, "s": s},
        ).scalar_one()
        # Même détection : l'ON CONFLICT ... WHERE IS DISTINCT FROM ne réécrit rien.
        _Q.upsert_detected_structures_bulk(sa_sync_conn, [DetectedStructure(addr, s, f)])
        xmin_after = sa_sync_conn.execute(
            text("SELECT xmin FROM address_structures WHERE address_id = :a AND structure_id = :s"),
            {"a": addr, "s": s},
        ).scalar_one()
        assert xmin_before == xmin_after  # pas de nouvelle version de ligne
