"""Tests d'intégration des requêtes de `pipeline.transformation.structures.address_resolution`."""

from pipeline.transformation.structures.address_resolution import (
    count_addresses,
    fetch_addresses_chunk,
)
from tests.integration.helpers.addresses import insert_address


class TestCountAddresses:
    def test_le_compte_suit_les_adresses_creees(self, sa_sync_conn):
        avant = count_addresses(sa_sync_conn)
        insert_address(sa_sync_conn, "A1", normalized_text="A1")
        insert_address(sa_sync_conn, "A2", normalized_text="A2")
        assert count_addresses(sa_sync_conn) == avant + 2


class TestFetchAddressesChunk:
    def test_returns_all_addresses(self, sa_sync_conn):
        a1 = insert_address(sa_sync_conn, "A1", normalized_text="A1")
        a2 = insert_address(sa_sync_conn, "A2", normalized_text="A2")
        rows = fetch_addresses_chunk(sa_sync_conn, after_id=0, limit=1000)
        ids = [addr_id for addr_id, _ in rows]
        assert a1 in ids and a2 in ids

    def test_keyset_after_id_and_limit(self, sa_sync_conn):
        """`after_id` exclut les ids <= seuil ; `limit` borne la tranche, triée par id."""
        a1 = insert_address(sa_sync_conn, "A1", normalized_text="A1")
        a2 = insert_address(sa_sync_conn, "A2", normalized_text="A2")
        a3 = insert_address(sa_sync_conn, "A3", normalized_text="A3")
        rows = fetch_addresses_chunk(sa_sync_conn, after_id=a1, limit=1)
        ids = [addr_id for addr_id, _ in rows]
        assert ids == [a2]  # a1 exclu (id <= after_id), a3 hors limite
        assert a3 > a2  # ordre par id garanti

    def test_returns_normalized_text_tuples(self, sa_sync_conn):
        addr_id = insert_address(sa_sync_conn, "Some address", normalized_text="Some address")
        rows = fetch_addresses_chunk(sa_sync_conn, after_id=0, limit=1000)
        assert all(isinstance(r, tuple) and len(r) == 2 for r in rows)
        row = next(r for r in rows if r[0] == addr_id)
        assert isinstance(row[0], int)
        assert row[1] == "Some address"
