"""Tests d'intégration pour `infrastructure.db.queries.person_duplicates` (§2.12 : async)."""

from infrastructure.db.queries.person_duplicates import (
    count_person_conflict_pairs,
    count_person_duplicates,
    next_person_conflict,
    next_person_duplicate,
    parse_skip_pairs,
)


async def _create_person(db, last="Dupond", first="Jean"):
    await db.execute(
        """
        INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized)
        VALUES (%s, %s, lower(%s), lower(%s)) RETURNING id
        """,
        (last, first, last, first),
    )
    row = await db.fetchone()
    return row["id"]


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


class TestParseSkipPairs:
    # parse_skip_pairs est pur Python (pas de DB) — reste sync.

    def test_empty_string(self):
        assert parse_skip_pairs("") == set()

    def test_single_pair(self):
        assert parse_skip_pairs("1-2") == {(1, 2)}

    def test_multiple_pairs(self):
        assert parse_skip_pairs("1-2,3-4,5-6") == {(1, 2), (3, 4), (5, 6)}

    def test_skips_malformed(self):
        assert parse_skip_pairs("1-2,bad,3-4,x-y") == {(1, 2), (3, 4)}


class TestCountPersonDuplicates:
    async def test_counts_same_initial(self, async_db):
        await _create_person(async_db, last="Dupond", first="Jean")
        await _create_person(async_db, last="Dupond", first="J")

        total = await count_person_duplicates(async_db)
        assert total >= 1


class TestNextPersonDuplicate:
    async def test_returns_candidate_pair(self, async_db):
        p1 = await _create_person(async_db, last="Dupond", first="Jean")
        p2 = await _create_person(async_db, last="Dupond", first="J")

        res = await next_person_duplicate(async_db, skip_pairs=None, offset=0)
        assert res is not None
        ids = {res["person_a"]["id"], res["person_b"]["id"]}
        assert ids == {p1, p2}

    async def test_skips_specified_pairs(self, async_db):
        p1 = await _create_person(async_db, last="Martin", first="Alice")
        p2 = await _create_person(async_db, last="Martin", first="A")

        # On skippe la paire → pas d'autre candidat → None
        skip = {(min(p1, p2), max(p1, p2))}
        res = await next_person_duplicate(async_db, skip_pairs=skip, offset=0)
        # Peut matcher d'autres paires dans le fixture global — on vérifie juste
        # que celle skippée n'apparaît pas
        if res is not None:
            got = {res["person_a"]["id"], res["person_b"]["id"]}
            assert got != {p1, p2}


class TestCountPersonConflictPairs:
    async def test_counts_conflicts(self, async_db):
        """Deux personnes distinctes référencées à la même position sur la même pub."""
        p1 = await _create_person(async_db, last="A")
        p2 = await _create_person(async_db, last="B")
        pub = await _create_pub(async_db)
        await async_db.execute(
            "INSERT INTO source_publications (source, source_id, title, publication_id) "
            "VALUES ('hal', 'h-1', 'X', %s) RETURNING id",
            (pub,),
        )
        row = await async_db.fetchone()
        sd = row["id"]
        await async_db.execute(
            "INSERT INTO source_persons (source, source_id, full_name) VALUES ('hal', 'sp-a', 'A') RETURNING id"
        )
        row = await async_db.fetchone()
        sp_a = row["id"]
        await async_db.execute(
            "INSERT INTO source_persons (source, source_id, full_name) VALUES ('openalex', 'sp-b', 'B') RETURNING id"
        )
        row = await async_db.fetchone()
        sp_b = row["id"]
        await async_db.execute(
            """
            INSERT INTO source_authorships (source, source_publication_id, source_person_id, author_position, person_id)
            VALUES ('hal', %s, %s, 0, %s)
            """,
            (sd, sp_a, p1),
        )
        await async_db.execute(
            """
            INSERT INTO source_authorships (source, source_publication_id, source_person_id, author_position, person_id)
            VALUES ('openalex', %s, %s, 0, %s)
            """,
            (sd, sp_b, p2),
        )

        count = await count_person_conflict_pairs(async_db)
        assert count >= 1


class TestNextPersonConflict:
    async def test_returns_none_when_no_conflict(self, async_db):
        # Pas de données → pas de conflit
        res = await next_person_conflict(async_db, async_db.connection, skip_pairs=set(), offset=0)
        assert res is None
