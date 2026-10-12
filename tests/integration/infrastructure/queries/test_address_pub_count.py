"""Tests de caractérisation pour `recompute_pub_count` (cache `addresses.pub_count`)."""

from sqlalchemy import text

from pipeline.publications.authorships.address_pub_count import AddressPubCountQueries

_Q = AddressPubCountQueries()
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_publication,
)


def _sa_for_pub(conn, pub_id, source_id):
    """source_authorship rattachée à la publication `pub_id`."""
    sd_id = insert_source_publication(conn, pub_id, source_id=source_id, pub_year=2024)
    return insert_signature(conn, sd_id)


def _link_address(conn, sa_id, raw_text):
    """Rattache une adresse (créée à la volée, dédupliquée par md5) à une signature via `source_authorship_addresses`."""
    addr_id = insert_address(conn, raw_text, reuse=True)
    insert_signature_address(conn, sa_id, address_id=addr_id)
    return addr_id


class TestRecomputePubCount:
    def test_counts_distinct_publications(self, sa_sync_conn):
        """pub_count = nb de publications canoniques distinctes, pas de signatures."""
        p1 = insert_publication(sa_sync_conn, "P1")
        p2 = insert_publication(sa_sync_conn, "P2")
        # 3 signatures sur la même adresse : 2 sur p1 (1 distinct), 1 sur p2.
        for sid, pub in (("h1", p1), ("h2", p1), ("h3", p2)):
            _link_address(sa_sync_conn, _sa_for_pub(sa_sync_conn, pub, sid), "Shared Address")

        _Q.recompute_pub_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT pub_count FROM addresses WHERE normalized_text = 'shared address'")
            ).scalar_one()
            == 2
        )

    def test_resets_orphan_to_zero(self, sa_sync_conn):
        """Une adresse sans lien mais au pub_count figé (cache périmé) repasse à 0."""
        addr = insert_address(sa_sync_conn, "Stale", pub_count=42)

        _Q.recompute_pub_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT pub_count FROM addresses WHERE id = :id"), {"id": addr}
            ).scalar_one()
            == 0
        )

    def test_ignores_source_publication_without_publication_id(self, sa_sync_conn):
        """Un document non rattaché (publication_id NULL) ne compte pas."""
        _link_address(sa_sync_conn, _sa_for_pub(sa_sync_conn, None, "orphan"), "Orphan Address")

        _Q.recompute_pub_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT pub_count FROM addresses WHERE normalized_text = 'orphan address'")
            ).scalar_one()
            == 0
        )
