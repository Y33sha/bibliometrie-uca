"""Tests des helpers async de lecture sur `subjects` consommés par
le router `/api/subjects`. La fixture `async_db` (transaction rollbackée
à la fin) est définie dans `tests/integration/conftest.py`."""

from infrastructure.db.queries.subjects import (
    count_subjects_async,
    get_subject_async,
    get_subject_neighbors_async,
    list_subjects_async,
)


async def _create_subject(async_db, *, label, usage_count=0, **kwargs):
    cols = ["label", "usage_count", *kwargs.keys()]
    placeholders = ", ".join(["%s"] * len(cols))
    await async_db.execute(
        f"INSERT INTO subjects ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id",
        (label, usage_count, *kwargs.values()),
    )
    return (await async_db.fetchone())["id"]


async def _link_cooccurrence(async_db, a_id, b_id, count):
    a, b = sorted([a_id, b_id])
    await async_db.execute(
        "INSERT INTO subject_cooccurrences (subject_a_id, subject_b_id, count) VALUES (%s, %s, %s)",
        (a, b, count),
    )


class TestListSubjectsAsync:
    async def test_orders_by_usage_count_desc(self, async_db):
        await _create_subject(async_db, label="rare", usage_count=2)
        await _create_subject(async_db, label="frequent", usage_count=50)
        await _create_subject(async_db, label="moderate", usage_count=10)
        items = await list_subjects_async(async_db)
        labels_ordered = [i["label"] for i in items]
        # Frequent en premier, rare en dernier.
        assert labels_ordered.index("frequent") < labels_ordered.index("moderate")
        assert labels_ordered.index("moderate") < labels_ordered.index("rare")

    async def test_filters_by_min_count(self, async_db):
        await _create_subject(async_db, label="low", usage_count=1)
        await _create_subject(async_db, label="high", usage_count=10)
        items = await list_subjects_async(async_db, min_count=5)
        labels = {i["label"] for i in items}
        assert "high" in labels
        assert "low" not in labels

    async def test_search_q_case_insensitive(self, async_db):
        await _create_subject(async_db, label="Climate Change", usage_count=10)
        await _create_subject(async_db, label="ATMOSPHERIC SCIENCE", usage_count=10)
        await _create_subject(async_db, label="biology", usage_count=10)
        items = await list_subjects_async(async_db, q="climate")
        assert len(items) == 1
        assert items[0]["label"] == "Climate Change"

    async def test_pagination(self, async_db):
        for i in range(10):
            await _create_subject(async_db, label=f"s{i:02d}", usage_count=10 - i)
        page1 = await list_subjects_async(async_db, limit=3, offset=0)
        page2 = await list_subjects_async(async_db, limit=3, offset=3)
        assert {i["label"] for i in page1}.isdisjoint({i["label"] for i in page2})
        assert len(page1) == 3 and len(page2) == 3


class TestCountSubjectsAsync:
    async def test_count_matches_filter(self, async_db):
        await _create_subject(async_db, label="a", usage_count=1)
        await _create_subject(async_db, label="b", usage_count=10)
        await _create_subject(async_db, label="c", usage_count=20)
        assert await count_subjects_async(async_db) == 3
        assert await count_subjects_async(async_db, min_count=5) == 2
        assert await count_subjects_async(async_db, q="b") == 1


class TestGetSubjectAsync:
    async def test_returns_dict(self, async_db):
        sid = await _create_subject(async_db, label="quantum", usage_count=42)
        s = await get_subject_async(async_db, sid)
        assert s is not None
        assert s["label"] == "quantum"
        assert s["usage_count"] == 42

    async def test_returns_none_for_missing(self, async_db):
        assert await get_subject_async(async_db, 999_999) is None


class TestGetSubjectNeighborsAsync:
    async def test_bidirectional_lookup(self, async_db):
        # Le sujet `center` a deux voisins via co-occurrences.
        center = await _create_subject(async_db, label="center", usage_count=10)
        left = await _create_subject(async_db, label="left", usage_count=8)
        right = await _create_subject(async_db, label="right", usage_count=5)
        # center est `b` ici (id plus grand que left), `a` là (id plus petit que right) — selon ordre d'insertion.
        await _link_cooccurrence(async_db, center, left, 5)
        await _link_cooccurrence(async_db, center, right, 3)
        neighbors = await get_subject_neighbors_async(async_db, center)
        labels = {n["label"] for n in neighbors}
        assert labels == {"left", "right"}

    async def test_orders_by_count_desc(self, async_db):
        c = await _create_subject(async_db, label="center", usage_count=10)
        n1 = await _create_subject(async_db, label="weak", usage_count=10)
        n2 = await _create_subject(async_db, label="strong", usage_count=10)
        await _link_cooccurrence(async_db, c, n1, 2)
        await _link_cooccurrence(async_db, c, n2, 50)
        neighbors = await get_subject_neighbors_async(async_db, c, min_count=1)
        assert neighbors[0]["label"] == "strong"
        assert neighbors[0]["cooccurrence_count"] == 50

    async def test_filters_by_min_count(self, async_db):
        c = await _create_subject(async_db, label="c", usage_count=10)
        keep = await _create_subject(async_db, label="keep", usage_count=10)
        skip = await _create_subject(async_db, label="skip", usage_count=10)
        await _link_cooccurrence(async_db, c, keep, 5)
        await _link_cooccurrence(async_db, c, skip, 1)
        neighbors = await get_subject_neighbors_async(async_db, c, min_count=3)
        labels = {n["label"] for n in neighbors}
        assert labels == {"keep"}

    async def test_limit(self, async_db):
        c = await _create_subject(async_db, label="c", usage_count=10)
        for i in range(5):
            n = await _create_subject(async_db, label=f"n{i}", usage_count=10)
            await _link_cooccurrence(async_db, c, n, 10 - i)
        neighbors = await get_subject_neighbors_async(async_db, c, limit=2)
        assert len(neighbors) == 2
