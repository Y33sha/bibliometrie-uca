"""Tests d'intégration pour `infrastructure.db.queries.publication_duplicates`."""

from infrastructure.db.queries.publication_duplicates import (
    get_publications_basic,
    next_pub_duplicate,
)


def _create_pub(db, title="Test Article For Dedup Testing", pub_year=2024, doi=None):
    db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
        VALUES (%s, lower(%s), %s, 'article', %s) RETURNING id
        """,
        (title, title, pub_year, doi),
    )
    return db.fetchone()["id"]


class TestNextPubDuplicate:
    def test_detects_candidate_pair_same_title(self, db):
        p1 = _create_pub(db, title="Same Title For Long Enough Detection To Trigger")
        p2 = _create_pub(db, title="Same Title For Long Enough Detection To Trigger")

        res = next_pub_duplicate(db, min_title_len=30, offset=0)
        assert res["total"] >= 1
        pair = res["pair"]
        assert pair is not None
        assert {pair["pub_a"]["id"], pair["pub_b"]["id"]} == {p1, p2}

    def test_no_candidate(self, db):
        _create_pub(db, title="A Unique Title That No One Else Will Use Here")
        _create_pub(db, title="Another Totally Distinct Title For This Test")

        res = next_pub_duplicate(db, min_title_len=30, offset=0)
        assert res["pair"] is None

    def test_excludes_pairs_in_distinct_publications(self, db):
        p1 = _create_pub(db, title="Same Title For Long Enough Detection To Trigger Me")
        p2 = _create_pub(db, title="Same Title For Long Enough Detection To Trigger Me")
        db.execute(
            "INSERT INTO distinct_publications (pub_id_a, pub_id_b) VALUES (%s, %s)",
            (min(p1, p2), max(p1, p2)),
        )
        res = next_pub_duplicate(db, min_title_len=30, offset=0)
        assert res["total"] == 0


class TestGetPublicationsBasic:
    def test_returns_only_requested(self, db):
        p1 = _create_pub(db, doi="10.1/a")
        p2 = _create_pub(db, doi="10.1/b")
        _create_pub(db, doi="10.1/c")

        res = get_publications_basic(db, [p1, p2])
        assert set(res.keys()) == {p1, p2}
        assert res[p1]["doi"] == "10.1/a"
