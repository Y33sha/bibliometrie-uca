"""Tests d'intégration pour `infrastructure.db.queries.publication_duplicates` (§2.12 : async)."""

from infrastructure.db.queries.publication_duplicates import (
    get_publications_basic,
    next_pub_duplicate,
)


async def _create_pub(db, title="Test Article For Dedup Testing", pub_year=2024, doi=None):
    await db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
        VALUES (%s, lower(%s), %s, 'article', %s) RETURNING id
        """,
        (title, title, pub_year, doi),
    )
    row = await db.fetchone()
    return row["id"]


class TestNextPubDuplicate:
    async def test_detects_candidate_pair_same_title(self, async_db):
        p1 = await _create_pub(async_db, title="Same Title For Long Enough Detection To Trigger")
        p2 = await _create_pub(async_db, title="Same Title For Long Enough Detection To Trigger")

        res = await next_pub_duplicate(async_db, min_title_len=30, offset=0)
        assert res["total"] >= 1
        pair = res["pair"]
        assert pair is not None
        assert {pair["pub_a"]["id"], pair["pub_b"]["id"]} == {p1, p2}

    async def test_no_candidate(self, async_db):
        await _create_pub(async_db, title="A Unique Title That No One Else Will Use Here")
        await _create_pub(async_db, title="Another Totally Distinct Title For This Test")

        res = await next_pub_duplicate(async_db, min_title_len=30, offset=0)
        assert res["pair"] is None

    async def test_excludes_pairs_in_distinct_publications(self, async_db):
        p1 = await _create_pub(async_db, title="Same Title For Long Enough Detection To Trigger Me")
        p2 = await _create_pub(async_db, title="Same Title For Long Enough Detection To Trigger Me")
        await async_db.execute(
            "INSERT INTO distinct_publications (pub_id_a, pub_id_b) VALUES (%s, %s)",
            (min(p1, p2), max(p1, p2)),
        )
        res = await next_pub_duplicate(async_db, min_title_len=30, offset=0)
        assert res["total"] == 0


class TestGetPublicationsBasic:
    async def test_returns_only_requested(self, async_db):
        p1 = await _create_pub(async_db, doi="10.1/a")
        p2 = await _create_pub(async_db, doi="10.1/b")
        await _create_pub(async_db, doi="10.1/c")

        res = await get_publications_basic(async_db, [p1, p2])
        assert set(res.keys()) == {p1, p2}
        assert res[p1]["doi"] == "10.1/a"
