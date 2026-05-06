"""Tests d'intégration pour `infrastructure.db.queries.publication_duplicates` (async)."""

from sqlalchemy import text

from infrastructure.db.queries.publication_duplicates import PgAsyncPublicationDuplicatesQueries


def _q(conn) -> PgAsyncPublicationDuplicatesQueries:
    return PgAsyncPublicationDuplicatesQueries(conn)


async def _create_pub(conn, title="Test Article For Dedup Testing", pub_year=2024, doi=None):
    row = (
        await conn.execute(
            text("""
                INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
                VALUES (:t, lower(:t), :y, 'article', :doi) RETURNING id
            """),
            {"t": title, "y": pub_year, "doi": doi},
        )
    ).one()
    return row.id


class TestNextPubDuplicate:
    async def test_detects_candidate_pair_same_title(self, sa_conn):
        p1 = await _create_pub(sa_conn, title="Same Title For Long Enough Detection To Trigger")
        p2 = await _create_pub(sa_conn, title="Same Title For Long Enough Detection To Trigger")

        res = await _q(sa_conn).next_pub_duplicate(min_title_len=30, offset=0)
        assert res["total"] >= 1
        pair = res["pair"]
        assert pair is not None
        assert {pair["pub_a"]["id"], pair["pub_b"]["id"]} == {p1, p2}

    async def test_no_candidate(self, sa_conn):
        await _create_pub(sa_conn, title="A Unique Title That No One Else Will Use Here")
        await _create_pub(sa_conn, title="Another Totally Distinct Title For This Test")

        res = await _q(sa_conn).next_pub_duplicate(min_title_len=30, offset=0)
        assert res["pair"] is None

    async def test_excludes_pairs_in_distinct_publications(self, sa_conn):
        p1 = await _create_pub(sa_conn, title="Same Title For Long Enough Detection To Trigger Me")
        p2 = await _create_pub(sa_conn, title="Same Title For Long Enough Detection To Trigger Me")
        await sa_conn.execute(
            text("INSERT INTO distinct_publications (pub_id_a, pub_id_b) VALUES (:a, :b)"),
            {"a": min(p1, p2), "b": max(p1, p2)},
        )
        res = await _q(sa_conn).next_pub_duplicate(min_title_len=30, offset=0)
        assert res["total"] == 0


class TestGetPublicationsBasic:
    async def test_returns_only_requested(self, sa_conn):
        p1 = await _create_pub(sa_conn, doi="10.1/a")
        p2 = await _create_pub(sa_conn, doi="10.1/b")
        await _create_pub(sa_conn, doi="10.1/c")

        res = await _q(sa_conn).get_publications_basic([p1, p2])
        assert set(res.keys()) == {p1, p2}
        assert res[p1]["doi"] == "10.1/a"
