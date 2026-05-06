"""Tests des lectures async sur `subjects` consommées par le router
`/api/subjects` (port `AsyncSubjectsQueries` / impl `PgAsyncSubjectsQueries`).
La fixture `sa_conn` (transaction rollbackée à la fin) est définie
dans `tests/integration/conftest.py`."""

from sqlalchemy import text

from infrastructure.db.queries.subjects import PgAsyncSubjectsQueries


def _q(conn) -> PgAsyncSubjectsQueries:
    return PgAsyncSubjectsQueries(conn)


async def _create_subject(conn, *, label, usage_count=0, **kwargs):
    cols = ["label", "usage_count", *kwargs.keys()]
    placeholders = ", ".join([f":{c}" for c in cols])
    binds = {"label": label, "usage_count": usage_count, **kwargs}
    row = (
        await conn.execute(
            text(f"INSERT INTO subjects ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id"),
            binds,
        )
    ).one()
    return row.id


async def _link_cooccurrence(conn, a_id, b_id, count):
    a, b = sorted([a_id, b_id])
    await conn.execute(
        text(
            "INSERT INTO subject_cooccurrences (subject_a_id, subject_b_id, count) "
            "VALUES (:a, :b, :c)"
        ),
        {"a": a, "b": b, "c": count},
    )


class TestListSubjects:
    async def test_orders_by_usage_count_desc(self, sa_conn):
        await _create_subject(sa_conn, label="rare", usage_count=2)
        await _create_subject(sa_conn, label="frequent", usage_count=50)
        await _create_subject(sa_conn, label="moderate", usage_count=10)
        items = await _q(sa_conn).list_subjects(q=None, limit=50, offset=0, min_count=1)
        labels_ordered = [i["label"] for i in items]
        # Frequent en premier, rare en dernier.
        assert labels_ordered.index("frequent") < labels_ordered.index("moderate")
        assert labels_ordered.index("moderate") < labels_ordered.index("rare")

    async def test_filters_by_min_count(self, sa_conn):
        await _create_subject(sa_conn, label="low", usage_count=1)
        await _create_subject(sa_conn, label="high", usage_count=10)
        items = await _q(sa_conn).list_subjects(q=None, limit=50, offset=0, min_count=5)
        labels = {i["label"] for i in items}
        assert "high" in labels
        assert "low" not in labels

    async def test_search_q_case_insensitive(self, sa_conn):
        await _create_subject(sa_conn, label="Climate Change", usage_count=10)
        await _create_subject(sa_conn, label="ATMOSPHERIC SCIENCE", usage_count=10)
        await _create_subject(sa_conn, label="biology", usage_count=10)
        items = await _q(sa_conn).list_subjects(q="climate", limit=50, offset=0, min_count=1)
        assert len(items) == 1
        assert items[0]["label"] == "Climate Change"

    async def test_pagination(self, sa_conn):
        for i in range(10):
            await _create_subject(sa_conn, label=f"s{i:02d}", usage_count=10 - i)
        page1 = await _q(sa_conn).list_subjects(q=None, limit=3, offset=0, min_count=1)
        page2 = await _q(sa_conn).list_subjects(q=None, limit=3, offset=3, min_count=1)
        assert {i["label"] for i in page1}.isdisjoint({i["label"] for i in page2})
        assert len(page1) == 3 and len(page2) == 3


class TestCountSubjects:
    async def test_count_matches_filter(self, sa_conn):
        await _create_subject(sa_conn, label="a", usage_count=1)
        await _create_subject(sa_conn, label="b", usage_count=10)
        await _create_subject(sa_conn, label="c", usage_count=20)
        q = _q(sa_conn)
        assert await q.count_subjects(q=None, min_count=1) == 3
        assert await q.count_subjects(q=None, min_count=5) == 2
        assert await q.count_subjects(q="b", min_count=1) == 1


class TestGetSubject:
    async def test_returns_dict(self, sa_conn):
        sid = await _create_subject(sa_conn, label="quantum", usage_count=42)
        s = await _q(sa_conn).get_subject(sid)
        assert s is not None
        assert s["label"] == "quantum"
        assert s["usage_count"] == 42

    async def test_returns_none_for_missing(self, sa_conn):
        assert await _q(sa_conn).get_subject(999_999) is None


class TestGetSubjectNeighbors:
    async def test_bidirectional_lookup(self, sa_conn):
        # Le sujet `center` a deux voisins via co-occurrences.
        center = await _create_subject(sa_conn, label="center", usage_count=10)
        left = await _create_subject(sa_conn, label="left", usage_count=8)
        right = await _create_subject(sa_conn, label="right", usage_count=5)
        await _link_cooccurrence(sa_conn, center, left, 5)
        await _link_cooccurrence(sa_conn, center, right, 3)
        neighbors = await _q(sa_conn).get_subject_neighbors(center, limit=20, min_count=2)
        labels = {n["label"] for n in neighbors}
        assert labels == {"left", "right"}

    async def test_orders_by_count_desc(self, sa_conn):
        c = await _create_subject(sa_conn, label="center", usage_count=10)
        n1 = await _create_subject(sa_conn, label="weak", usage_count=10)
        n2 = await _create_subject(sa_conn, label="strong", usage_count=10)
        await _link_cooccurrence(sa_conn, c, n1, 2)
        await _link_cooccurrence(sa_conn, c, n2, 50)
        neighbors = await _q(sa_conn).get_subject_neighbors(c, limit=20, min_count=1)
        assert neighbors[0]["label"] == "strong"
        assert neighbors[0]["cooccurrence_count"] == 50

    async def test_filters_by_min_count(self, sa_conn):
        c = await _create_subject(sa_conn, label="c", usage_count=10)
        keep = await _create_subject(sa_conn, label="keep", usage_count=10)
        skip = await _create_subject(sa_conn, label="skip", usage_count=10)
        await _link_cooccurrence(sa_conn, c, keep, 5)
        await _link_cooccurrence(sa_conn, c, skip, 1)
        neighbors = await _q(sa_conn).get_subject_neighbors(c, limit=20, min_count=3)
        labels = {n["label"] for n in neighbors}
        assert labels == {"keep"}

    async def test_limit(self, sa_conn):
        c = await _create_subject(sa_conn, label="c", usage_count=10)
        for i in range(5):
            n = await _create_subject(sa_conn, label=f"n{i}", usage_count=10)
            await _link_cooccurrence(sa_conn, c, n, 10 - i)
        neighbors = await _q(sa_conn).get_subject_neighbors(c, limit=2, min_count=2)
        assert len(neighbors) == 2
