"""Tests des lectures sync sur `subjects` consommées par le router
`/api/subjects` (port `SubjectsQueries` / impl `PgSubjectsQueries`).
La fixture `sa_sync_conn` (transaction rollbackée à la fin) est définie
dans `tests/integration/conftest.py`."""

from sqlalchemy import text

from infrastructure.queries.api.subjects import PgSubjectsQueries


def _q(conn) -> PgSubjectsQueries:
    return PgSubjectsQueries(conn)


def _create_subject(conn, *, label, usage_count=0, **kwargs):
    cols = ["label", "usage_count", *kwargs.keys()]
    placeholders = ", ".join([f":{c}" for c in cols])
    binds = {"label": label, "usage_count": usage_count, **kwargs}
    row = conn.execute(
        text(f"INSERT INTO subjects ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id"),
        binds,
    ).one()
    return row.id


def _link_cooccurrence(conn, a_id, b_id, count):
    """Crée `count` publications liées aux deux sujets, de sorte que la matview
    `subject_cooccurrences` produira (a, b) avec ce count au prochain refresh.
    Ne rafraîchit pas la matview — appeler `_refresh()` à la fin du setup."""
    a, b = sorted([a_id, b_id])
    for _ in range(count):
        pub_id = conn.execute(
            text(
                "INSERT INTO publications (title, pub_year, doc_type) "
                "VALUES ('cooc-seed', 2024, 'article') RETURNING id"
            )
        ).scalar_one()
        for s in (a, b):
            conn.execute(
                text(
                    "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                    "VALUES (:p, :s, 'hal')"
                ),
                {"p": pub_id, "s": s},
            )


def _refresh(conn):
    conn.execute(text("REFRESH MATERIALIZED VIEW subject_cooccurrences"))


class TestListSubjects:
    def test_orders_by_usage_count_desc(self, sa_sync_conn):
        _create_subject(sa_sync_conn, label="rare", usage_count=2)
        _create_subject(sa_sync_conn, label="frequent", usage_count=50)
        _create_subject(sa_sync_conn, label="moderate", usage_count=10)
        items = _q(sa_sync_conn).list_subjects(q=None, limit=50, offset=0, min_usage_count=1)
        labels_ordered = [i.label for i in items]
        # Frequent en premier, rare en dernier.
        assert labels_ordered.index("frequent") < labels_ordered.index("moderate")
        assert labels_ordered.index("moderate") < labels_ordered.index("rare")

    def test_filters_by_min_usage_count(self, sa_sync_conn):
        _create_subject(sa_sync_conn, label="low", usage_count=1)
        _create_subject(sa_sync_conn, label="high", usage_count=10)
        items = _q(sa_sync_conn).list_subjects(q=None, limit=50, offset=0, min_usage_count=5)
        labels = {i.label for i in items}
        assert "high" in labels
        assert "low" not in labels

    def test_search_ignores_accents(self, sa_sync_conn):
        """Régression : `lower(label) LIKE` était sensible aux accents."""
        _create_subject(sa_sync_conn, label="épidémiologie quantique")
        queries = _q(sa_sync_conn)

        for term in ("epidemiologie quantique", "épidémiologie quantique"):
            found = queries.list_subjects(q=term, limit=10, offset=0, min_usage_count=0)
            assert any(s.label == "épidémiologie quantique" for s in found), term

    def test_search_q_case_insensitive(self, sa_sync_conn):
        _create_subject(sa_sync_conn, label="Climate Change", usage_count=10)
        _create_subject(sa_sync_conn, label="ATMOSPHERIC SCIENCE", usage_count=10)
        _create_subject(sa_sync_conn, label="biology", usage_count=10)
        items = _q(sa_sync_conn).list_subjects(q="climate", limit=50, offset=0, min_usage_count=1)
        assert len(items) == 1
        assert items[0].label == "Climate Change"

    def test_pagination(self, sa_sync_conn):
        for i in range(10):
            _create_subject(sa_sync_conn, label=f"s{i:02d}", usage_count=10 - i)
        page1 = _q(sa_sync_conn).list_subjects(q=None, limit=3, offset=0, min_usage_count=1)
        page2 = _q(sa_sync_conn).list_subjects(q=None, limit=3, offset=3, min_usage_count=1)
        assert {i.label for i in page1}.isdisjoint({i.label for i in page2})
        assert len(page1) == 3 and len(page2) == 3


class TestCountSubjects:
    def test_count_matches_filter(self, sa_sync_conn):
        _create_subject(sa_sync_conn, label="a", usage_count=1)
        _create_subject(sa_sync_conn, label="b", usage_count=10)
        _create_subject(sa_sync_conn, label="c", usage_count=20)
        q = _q(sa_sync_conn)
        assert q.count_subjects(q=None, min_usage_count=1) == 3
        assert q.count_subjects(q=None, min_usage_count=5) == 2
        assert q.count_subjects(q="b", min_usage_count=1) == 1


class TestGetSubject:
    def test_returns_dto(self, sa_sync_conn):
        sid = _create_subject(sa_sync_conn, label="quantum", usage_count=42)
        s = _q(sa_sync_conn).get_subject(sid)
        assert s is not None
        assert s.label == "quantum"
        assert s.usage_count == 42

    def test_returns_none_for_missing(self, sa_sync_conn):
        assert _q(sa_sync_conn).get_subject(999_999) is None


class TestGetSubjectNeighbors:
    def test_bidirectional_lookup(self, sa_sync_conn):
        # Le sujet `center` a deux voisins via co-occurrences.
        center = _create_subject(sa_sync_conn, label="center", usage_count=10)
        left = _create_subject(sa_sync_conn, label="left", usage_count=8)
        right = _create_subject(sa_sync_conn, label="right", usage_count=5)
        _link_cooccurrence(sa_sync_conn, center, left, 5)
        _link_cooccurrence(sa_sync_conn, center, right, 3)
        _refresh(sa_sync_conn)
        neighbors = _q(sa_sync_conn).get_subject_neighbors(
            center, limit=20, min_cooccurrence_count=2
        )
        labels = {n.label for n in neighbors}
        assert labels == {"left", "right"}

    def test_orders_by_count_desc(self, sa_sync_conn):
        c = _create_subject(sa_sync_conn, label="center", usage_count=10)
        n1 = _create_subject(sa_sync_conn, label="weak", usage_count=10)
        n2 = _create_subject(sa_sync_conn, label="strong", usage_count=10)
        _link_cooccurrence(sa_sync_conn, c, n1, 2)
        _link_cooccurrence(sa_sync_conn, c, n2, 50)
        _refresh(sa_sync_conn)
        neighbors = _q(sa_sync_conn).get_subject_neighbors(c, limit=20, min_cooccurrence_count=1)
        assert neighbors[0].label == "strong"
        assert neighbors[0].cooccurrence_count == 50

    def test_filters_by_min_cooccurrence_count(self, sa_sync_conn):
        c = _create_subject(sa_sync_conn, label="c", usage_count=10)
        keep = _create_subject(sa_sync_conn, label="keep", usage_count=10)
        skip = _create_subject(sa_sync_conn, label="skip", usage_count=10)
        _link_cooccurrence(sa_sync_conn, c, keep, 5)
        # count=1 ne franchit pas le seuil de la matview (>= 2) — la paire
        # (c, skip) n'apparaît pas indépendamment du filtre de co-occurrences minimales à la lecture.
        _link_cooccurrence(sa_sync_conn, c, skip, 1)
        _refresh(sa_sync_conn)
        neighbors = _q(sa_sync_conn).get_subject_neighbors(c, limit=20, min_cooccurrence_count=3)
        labels = {n.label for n in neighbors}
        assert labels == {"keep"}

    def test_limit(self, sa_sync_conn):
        c = _create_subject(sa_sync_conn, label="c", usage_count=10)
        for i in range(5):
            n = _create_subject(sa_sync_conn, label=f"n{i}", usage_count=10)
            _link_cooccurrence(sa_sync_conn, c, n, 10 - i)
        _refresh(sa_sync_conn)
        neighbors = _q(sa_sync_conn).get_subject_neighbors(c, limit=2, min_cooccurrence_count=2)
        assert len(neighbors) == 2
