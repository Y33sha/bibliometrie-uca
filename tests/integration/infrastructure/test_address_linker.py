"""Tests de caractérisation pour `recompute_pub_count` (cache `addresses.pub_count`)."""

from sqlalchemy import text

from infrastructure.repositories.address_linker import recompute_pub_count
from tests.integration.helpers.authorships import upsert_identity


def _new_pub(conn, title):
    return conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES (:t, lower(:t), 2024, 'article') RETURNING id"
        ),
        {"t": title},
    ).scalar_one()


def _sa_for_pub(conn, pub_id, source_id):
    """source_authorship rattachée à la publication `pub_id`."""
    sd_id = conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title, pub_year, publication_id) "
            "VALUES ('hal', :sid, 'X', 2024, :pub_id) RETURNING id"
        ),
        {"sid": source_id, "pub_id": pub_id},
    ).scalar_one()
    return conn.execute(
        text(
            "INSERT INTO source_authorships (source, source_publication_id, author_position, identity_id) "
            "VALUES ('hal', :sd_id, 0, :iid) RETURNING id"
        ),
        {"sd_id": sd_id, "iid": upsert_identity(conn)},
    ).scalar_one()


def _link_address(conn, sa_id, raw_text):
    """Rattache une adresse (créée à la volée, dédupliquée par md5) à une signature via `source_authorship_addresses`."""
    addr_id = conn.execute(
        text(
            "INSERT INTO addresses (raw_text, normalized_text) VALUES (:r, lower(:r)) "
            "ON CONFLICT (md5(raw_text)) DO UPDATE SET raw_text = EXCLUDED.raw_text RETURNING id"
        ),
        {"r": raw_text},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO source_authorship_addresses (source_authorship_id, address_id) "
            "VALUES (:sa, :addr) ON CONFLICT DO NOTHING"
        ),
        {"sa": sa_id, "addr": addr_id},
    )
    return addr_id


class TestRecomputePubCount:
    def test_counts_distinct_publications(self, sa_sync_conn):
        """pub_count = nb de publications canoniques distinctes, pas de signatures."""
        p1 = _new_pub(sa_sync_conn, "P1")
        p2 = _new_pub(sa_sync_conn, "P2")
        # 3 signatures sur la même adresse : 2 sur p1 (1 distinct), 1 sur p2.
        for sid, pub in (("h1", p1), ("h2", p1), ("h3", p2)):
            _link_address(sa_sync_conn, _sa_for_pub(sa_sync_conn, pub, sid), "Shared Address")

        recompute_pub_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT pub_count FROM addresses WHERE normalized_text = 'shared address'")
            ).scalar_one()
            == 2
        )

    def test_resets_orphan_to_zero(self, sa_sync_conn):
        """Une adresse sans lien mais au pub_count figé (cache périmé) repasse à 0."""
        addr = sa_sync_conn.execute(
            text(
                "INSERT INTO addresses (raw_text, normalized_text, pub_count) "
                "VALUES ('Stale', 'stale', 42) RETURNING id"
            )
        ).scalar_one()

        recompute_pub_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT pub_count FROM addresses WHERE id = :id"), {"id": addr}
            ).scalar_one()
            == 0
        )

    def test_ignores_source_publication_without_publication_id(self, sa_sync_conn):
        """Un document non rattaché (publication_id NULL) ne compte pas."""
        sd_id = sa_sync_conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, pub_year) "
                "VALUES ('hal', 'orphan', 'X', 2024) RETURNING id"
            )
        ).scalar_one()
        sa_id = sa_sync_conn.execute(
            text(
                "INSERT INTO source_authorships (source, source_publication_id, author_position, identity_id) "
                "VALUES ('hal', :sd, 0, :iid) RETURNING id"
            ),
            {"sd": sd_id, "iid": upsert_identity(sa_sync_conn)},
        ).scalar_one()
        _link_address(sa_sync_conn, sa_id, "Orphan Address")

        recompute_pub_count(sa_sync_conn)

        assert (
            sa_sync_conn.execute(
                text("SELECT pub_count FROM addresses WHERE normalized_text = 'orphan address'")
            ).scalar_one()
            == 0
        )
