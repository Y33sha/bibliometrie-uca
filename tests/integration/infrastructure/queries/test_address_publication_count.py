"""Tests de caractérisation pour `recompute_address_publication_count` (cache `addresses.publication_count`)."""

from sqlalchemy import text

from pipeline.transformation.publications.contributions.address_publication_count import (
    recompute_address_publication_count,
)
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)


def _source_contribution_for_publication(conn, publication_id, source_id):
    """source_contribution rattachée à la publication `publication_id`."""
    source_record_id = insert_source_record(
        conn, publication_id, source_id=source_id, publication_year=2024
    )
    return insert_source_contribution(conn, source_record_id)


def _link_address(conn, source_contribution_id, raw_text):
    """Rattache une adresse (créée à la volée, dédupliquée par md5) à une contribution source via `source_contribution_addresses`."""
    addr_id = insert_address(conn, raw_text, reuse=True)
    insert_source_contribution_address(conn, source_contribution_id, address_id=addr_id)
    return addr_id


class TestRecomputePublicationCount:
    def test_counts_distinct_publications(self, sa_sync_conn):
        """publication_count = nb de publications distinctes, pas de contributions sources."""
        p1 = insert_publication(sa_sync_conn, "P1")
        p2 = insert_publication(sa_sync_conn, "P2")
        # 3 contributions sources sur la même adresse : 2 sur p1 (1 distinct), 1 sur p2.
        for sid, publication in (("h1", p1), ("h2", p1), ("h3", p2)):
            _link_address(
                sa_sync_conn,
                _source_contribution_for_publication(sa_sync_conn, publication, sid),
                "Shared Address",
            )

        recompute_address_publication_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text(
                    "SELECT publication_count FROM addresses WHERE normalized_text = 'shared address'"
                )
            ).scalar_one()
            == 2
        )

    def test_resets_orphan_to_zero(self, sa_sync_conn):
        """Une adresse sans lien mais au publication_count figé (cache périmé) repasse à 0."""
        addr = insert_address(sa_sync_conn, "Stale", publication_count=42)

        recompute_address_publication_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT publication_count FROM addresses WHERE id = :id"), {"id": addr}
            ).scalar_one()
            == 0
        )

    def test_ignores_source_record_without_publication_id(self, sa_sync_conn):
        """Un document non rattaché (publication_id NULL) ne compte pas."""
        _link_address(
            sa_sync_conn,
            _source_contribution_for_publication(sa_sync_conn, None, "orphan"),
            "Orphan Address",
        )

        recompute_address_publication_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text(
                    "SELECT publication_count FROM addresses WHERE normalized_text = 'orphan address'"
                )
            ).scalar_one()
            == 0
        )
