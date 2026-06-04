"""Tests d'intégration pour `infrastructure.queries.api.publication_duplicates`."""

from sqlalchemy import text

from infrastructure.queries.api.publication_duplicates import PgPublicationDuplicatesQueries


def _q(conn) -> PgPublicationDuplicatesQueries:
    return PgPublicationDuplicatesQueries(conn)


def _create_pub(conn, title="Test Article For Dedup Testing", pub_year=2024, doi=None):
    row = conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
            VALUES (:t, lower(:t), :y, 'article', :doi) RETURNING id
        """),
        {"t": title, "y": pub_year, "doi": doi},
    ).one()
    return row.id


class TestNextPubDuplicate:
    def test_detects_candidate_pair_same_title(self, sa_sync_conn):
        p1 = _create_pub(sa_sync_conn, title="Same Title For Long Enough Detection To Trigger")
        p2 = _create_pub(sa_sync_conn, title="Same Title For Long Enough Detection To Trigger")

        res = _q(sa_sync_conn).next_pub_duplicate(min_title_len=30, offset=0)
        assert res.total >= 1
        pair = res.pair
        assert pair is not None
        assert {pair.pub_a.id, pair.pub_b.id} == {p1, p2}

    def test_no_candidate(self, sa_sync_conn):
        _create_pub(sa_sync_conn, title="A Unique Title That No One Else Will Use Here")
        _create_pub(sa_sync_conn, title="Another Totally Distinct Title For This Test")

        res = _q(sa_sync_conn).next_pub_duplicate(min_title_len=30, offset=0)
        assert res.pair is None

    def test_excludes_pairs_in_distinct_publications(self, sa_sync_conn):
        p1 = _create_pub(sa_sync_conn, title="Same Title For Long Enough Detection To Trigger Me")
        p2 = _create_pub(sa_sync_conn, title="Same Title For Long Enough Detection To Trigger Me")
        sa_sync_conn.execute(
            text("INSERT INTO distinct_publications (pub_id_a, pub_id_b) VALUES (:a, :b)"),
            {"a": min(p1, p2), "b": max(p1, p2)},
        )
        res = _q(sa_sync_conn).next_pub_duplicate(min_title_len=30, offset=0)
        assert res.total == 0


class TestExistingPublicationIds:
    def test_returns_only_existing(self, sa_sync_conn):
        p1 = _create_pub(sa_sync_conn, doi="10.1/a")
        p2 = _create_pub(sa_sync_conn, doi="10.1/b")
        _create_pub(sa_sync_conn, doi="10.1/c")

        res = _q(sa_sync_conn).existing_publication_ids((p1, p2, 999_999))
        assert res == {p1, p2}

    def test_returns_empty_for_empty_input(self, sa_sync_conn):
        assert _q(sa_sync_conn).existing_publication_ids(()) == set()
