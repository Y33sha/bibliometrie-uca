"""Tests d'intégration pour `infrastructure.db.queries.duplicates`."""

from infrastructure.db.queries.duplicates import (
    count_person_conflict_pairs,
    count_person_duplicates,
    get_publications_basic,
    next_person_conflict,
    next_person_duplicate,
    next_pub_duplicate,
    parse_skip_pairs,
)


def _create_person(db, last="Dupond", first="Jean"):
    db.execute(
        """
        INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized)
        VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id
        """,
        (last, first, last, first),
    )
    return db.fetchone()["id"]


def _create_pub(db, title="Test Article For Dedup Testing", pub_year=2024, doi=None):
    db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
        VALUES (%s, lower(%s), %s, 'article', %s) RETURNING id
        """,
        (title, title, pub_year, doi),
    )
    return db.fetchone()["id"]


class TestParseSkipPairs:
    def test_empty_string(self):
        assert parse_skip_pairs("") == set()

    def test_single_pair(self):
        assert parse_skip_pairs("1-2") == {(1, 2)}

    def test_multiple_pairs(self):
        assert parse_skip_pairs("1-2,3-4,5-6") == {(1, 2), (3, 4), (5, 6)}

    def test_skips_malformed(self):
        assert parse_skip_pairs("1-2,bad,3-4,x-y") == {(1, 2), (3, 4)}


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


class TestCountPersonDuplicates:
    def test_counts_same_initial(self, db):
        _create_person(db, last="Dupond", first="Jean")
        _create_person(db, last="Dupond", first="J")

        total = count_person_duplicates(db)
        assert total >= 1


class TestNextPersonDuplicate:
    def test_returns_candidate_pair(self, db):
        p1 = _create_person(db, last="Dupond", first="Jean")
        p2 = _create_person(db, last="Dupond", first="J")

        res = next_person_duplicate(db, skip_pairs=None, offset=0)
        assert res is not None
        ids = {res["person_a"]["id"], res["person_b"]["id"]}
        assert ids == {p1, p2}

    def test_skips_specified_pairs(self, db):
        p1 = _create_person(db, last="Martin", first="Alice")
        p2 = _create_person(db, last="Martin", first="A")

        # On skippe la paire → pas d'autre candidat → None
        skip = {(min(p1, p2), max(p1, p2))}
        res = next_person_duplicate(db, skip_pairs=skip, offset=0)
        # Peut matcher d'autres paires dans le fixture global — on vérifie juste
        # que celle skippée n'apparaît pas
        if res is not None:
            got = {res["person_a"]["id"], res["person_b"]["id"]}
            assert got != {p1, p2}


class TestCountPersonConflictPairs:
    def test_counts_conflicts(self, db):
        """Deux personnes distinctes référencées à la même position sur la même pub."""
        p1 = _create_person(db, last="A")
        p2 = _create_person(db, last="B")
        pub = _create_pub(db)
        db.execute(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('hal', 'h-1', 'X', %s) RETURNING id",
            (pub,),
        )
        sd = db.fetchone()["id"]
        db.execute(
            "INSERT INTO source_persons (source, source_id, full_name) VALUES ('hal', 'sp-a', 'A') RETURNING id"
        )
        sp_a = db.fetchone()["id"]
        db.execute(
            "INSERT INTO source_persons (source, source_id, full_name) VALUES ('openalex', 'sp-b', 'B') RETURNING id"
        )
        sp_b = db.fetchone()["id"]
        db.execute(
            """
            INSERT INTO source_authorships (source, source_publication_id, source_person_id, author_position, person_id)
            VALUES ('hal', %s, %s, 0, %s)
            """,
            (sd, sp_a, p1),
        )
        db.execute(
            """
            INSERT INTO source_authorships (source, source_publication_id, source_person_id, author_position, person_id)
            VALUES ('openalex', %s, %s, 0, %s)
            """,
            (sd, sp_b, p2),
        )

        count = count_person_conflict_pairs(db)
        assert count >= 1


class TestNextPersonConflict:
    def test_returns_none_when_no_conflict(self, db):
        # Pas de données → pas de conflit
        res = next_person_conflict(db, db.connection, skip_pairs=set(), offset=0)
        assert res is None
