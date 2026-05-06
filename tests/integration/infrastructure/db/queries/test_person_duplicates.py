"""Tests d'intégration pour `infrastructure.db.queries.person_duplicates` (async)."""

from sqlalchemy import text

from application.ports.person_duplicates_queries import parse_skip_pairs
from infrastructure.db.queries.person_duplicates import PgAsyncPersonDuplicatesQueries


def _q(conn) -> PgAsyncPersonDuplicatesQueries:
    return PgAsyncPersonDuplicatesQueries(conn)


async def _create_person(conn, last="Dupond", first="Jean"):
    row = (
        await conn.execute(
            text("""
                INSERT INTO persons
                    (last_name, first_name, last_name_normalized, first_name_normalized)
                VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id
            """),
            {"l": last, "f": first},
        )
    ).one()
    return row.id


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
    async def test_counts_same_initial(self, sa_conn):
        await _create_person(sa_conn, last="Dupond", first="Jean")
        await _create_person(sa_conn, last="Dupond", first="J")

        total = await _q(sa_conn).count_person_duplicates()
        assert total >= 1


class TestNextPersonDuplicate:
    async def test_returns_candidate_pair(self, sa_conn):
        p1 = await _create_person(sa_conn, last="Dupond", first="Jean")
        p2 = await _create_person(sa_conn, last="Dupond", first="J")

        res = await _q(sa_conn).next_person_duplicate(skip_pairs=None, offset=0)
        assert res is not None
        ids = {res["person_a"]["id"], res["person_b"]["id"]}
        assert ids == {p1, p2}

    async def test_skips_specified_pairs(self, sa_conn):
        p1 = await _create_person(sa_conn, last="Martin", first="Alice")
        p2 = await _create_person(sa_conn, last="Martin", first="A")

        # On skippe la paire → pas d'autre candidat → None
        skip = {(min(p1, p2), max(p1, p2))}
        res = await _q(sa_conn).next_person_duplicate(skip_pairs=skip, offset=0)
        # Peut matcher d'autres paires dans le fixture global — on vérifie juste
        # que celle skippée n'apparaît pas
        if res is not None:
            got = {res["person_a"]["id"], res["person_b"]["id"]}
            assert got != {p1, p2}


class TestCountPersonConflictPairs:
    async def test_counts_conflicts(self, sa_conn):
        """Deux personnes distinctes référencées à la même position sur la même pub."""
        p1 = await _create_person(sa_conn, last="A")
        p2 = await _create_person(sa_conn, last="B")
        pub = await _create_pub(sa_conn)
        sd_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO source_publications (source, source_id, title, publication_id) "
                    "VALUES ('hal', 'h-1', 'X', :p) RETURNING id"
                ),
                {"p": pub},
            )
        ).one()
        sd = sd_row.id
        sp_a_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO source_persons (source, source_id, full_name) "
                    "VALUES ('hal', 'sp-a', 'A') RETURNING id"
                )
            )
        ).one()
        sp_a = sp_a_row.id
        sp_b_row = (
            await sa_conn.execute(
                text(
                    "INSERT INTO source_persons (source, source_id, full_name) "
                    "VALUES ('openalex', 'sp-b', 'B') RETURNING id"
                )
            )
        ).one()
        sp_b = sp_b_row.id
        await sa_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, source_person_id, author_position, person_id)
                VALUES ('hal', :sd, :sp, 0, :pid)
            """),
            {"sd": sd, "sp": sp_a, "pid": p1},
        )
        await sa_conn.execute(
            text("""
                INSERT INTO source_authorships
                    (source, source_publication_id, source_person_id, author_position, person_id)
                VALUES ('openalex', :sd, :sp, 0, :pid)
            """),
            {"sd": sd, "sp": sp_b, "pid": p2},
        )

        count = await _q(sa_conn).count_person_conflict_pairs()
        assert count >= 1


class TestNextPersonConflict:
    async def test_returns_none_when_no_conflict(self, sa_conn):
        # Pas de données → pas de conflit
        res = await _q(sa_conn).next_person_conflict(skip_pairs=set(), offset=0)
        assert res is None
