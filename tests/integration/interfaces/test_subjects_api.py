"""Tests d'intégration pour le router `interfaces.api.routers.subjects`.

Couvre :
- GET /api/subjects (liste, pagination, search, min_count)
- GET /api/subjects/{id} (detail, neighbors, 404)
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest
from psycopg.rows import dict_row

_DB_ARGS = {
    "dbname": "bibliometrie_test",
    "user": os.environ["DB_USER"],
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "5432")),
}
if os.environ.get("DB_PASSWORD"):
    _DB_ARGS["password"] = os.environ["DB_PASSWORD"]


@contextmanager
def _pool():
    conn = psycopg.connect(**_DB_ARGS, row_factory=dict_row)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_subject(label: str | None = None, usage_count: int = 1) -> int:
    label = label or _uniq("Subject")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO subjects (label, usage_count) VALUES (%s, %s) RETURNING id",
            (label, usage_count),
        )
        return cur.fetchone()["id"]


def _seed_cooccurrence(subject_a_id: int, subject_b_id: int, count: int) -> None:
    """Crée `count` publications liées aux deux sujets puis rafraîchit la
    matview pour produire la paire (a, b) avec ce count. Seuil de la matview
    `count >= 2` : passer un count < 2 ne fera pas apparaître la paire."""
    a, b = sorted([subject_a_id, subject_b_id])
    with _pool() as cur:
        for _ in range(count):
            cur.execute(
                "INSERT INTO publications (title, pub_year, doc_type) "
                "VALUES ('cooc-seed', 2024, 'article') RETURNING id"
            )
            pub_id = cur.fetchone()["id"]
            for s in (a, b):
                cur.execute(
                    "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                    "VALUES (%s, %s, 'hal')",
                    (pub_id, s),
                )
        cur.execute("REFRESH MATERIALIZED VIEW subject_cooccurrences")


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        # Cascade vide publication_subjects ; publications 'cooc-seed' du
        # helper `_seed_cooccurrence` sont nettoyées explicitement.
        cur.execute("TRUNCATE TABLE subjects RESTART IDENTITY CASCADE")
        cur.execute("DELETE FROM publications WHERE title = 'cooc-seed'")
        cur.execute("REFRESH MATERIALIZED VIEW subject_cooccurrences")


class TestListSubjects:
    def test_returns_paginated_shape(self, client):
        r = client.get("/api/subjects")
        assert r.status_code == 200
        body = r.json()
        assert {"items", "total", "page", "per_page"} <= set(body)

    def test_per_page_above_limit_rejected(self, client):
        # `per_page` Query(le=200) → > 200 = 422.
        r = client.get("/api/subjects", params={"per_page": 500})
        assert r.status_code == 422

    def test_page_below_one_rejected(self, client):
        r = client.get("/api/subjects", params={"page": 0})
        assert r.status_code == 422

    def test_min_count_below_one_rejected(self, client):
        r = client.get("/api/subjects", params={"min_count": 0})
        assert r.status_code == 422

    def test_search_q_param(self, client):
        label = _uniq("FindMeSubject")
        sid = _seed_subject(label=label, usage_count=10)
        r = client.get("/api/subjects", params={"q": label.lower()})
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert sid in ids

    def test_min_count_filter(self, client):
        low = _seed_subject(_uniq("LowCount"), usage_count=1)
        high = _seed_subject(_uniq("HighCount"), usage_count=50)
        # min_count=10 doit filtrer `low` mais retenir `high`.
        r = client.get("/api/subjects", params={"min_count": 10, "per_page": 200})
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert high in ids
        assert low not in ids


class TestGetSubject:
    def test_404_when_unknown(self, client):
        r = client.get("/api/subjects/999999999")
        assert r.status_code == 404

    def test_returns_subject_with_empty_neighbors(self, client):
        label = _uniq("DetailSubject")
        sid = _seed_subject(label=label, usage_count=5)
        r = client.get(f"/api/subjects/{sid}")
        assert r.status_code == 200
        body = r.json()
        assert body["subject"]["id"] == sid
        assert body["subject"]["label"] == label
        assert body["neighbors"] == []

    def test_returns_neighbors_when_cooccurrences_exist(self, client):
        s_main = _seed_subject(_uniq("Main"), usage_count=10)
        s_n1 = _seed_subject(_uniq("Neighbor1"), usage_count=8)
        s_n2 = _seed_subject(_uniq("Neighbor2"), usage_count=5)
        _seed_cooccurrence(s_main, s_n1, count=10)
        _seed_cooccurrence(s_main, s_n2, count=5)

        r = client.get(f"/api/subjects/{s_main}", params={"min_cooccurrence": 1})
        assert r.status_code == 200
        neighbors = r.json()["neighbors"]
        ids = [n["id"] for n in neighbors]
        assert s_n1 in ids
        assert s_n2 in ids

    def test_min_cooccurrence_filters(self, client):
        s_main = _seed_subject(_uniq("MainFilter"), usage_count=10)
        s_weak = _seed_subject(_uniq("WeakNeighbor"), usage_count=8)
        _seed_cooccurrence(s_main, s_weak, count=2)

        r = client.get(f"/api/subjects/{s_main}", params={"min_cooccurrence": 5})
        assert r.status_code == 200
        # Lien de count=2 < min_cooccurrence=5 → filtré.
        ids = [n["id"] for n in r.json()["neighbors"]]
        assert s_weak not in ids

    def test_neighbors_limit_param_validation(self, client):
        # Query(ge=1, le=100) — > 100 = 422.
        s = _seed_subject()
        r = client.get(f"/api/subjects/{s}", params={"neighbors_limit": 500})
        assert r.status_code == 422
