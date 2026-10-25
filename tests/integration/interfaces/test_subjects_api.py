"""Tests d'intégration pour le router `interfaces.api.routers.subjects`.

Couvre :
- GET /api/subjects (liste, pagination, search, min_count)
- GET /api/subjects/{id} (detail, neighbors, 404)
"""

from __future__ import annotations

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_publication,
    seed_publication_subject,
    seed_subject,
    uniq,
)


def _seed_cooccurrence(subject_a_id: int, subject_b_id: int, count: int) -> None:
    """Crée `count` publications liées aux deux sujets puis rafraîchit la
    matview pour produire la paire (a, b) avec ce count. Seuil de la matview
    `count >= 2` : passer un count < 2 ne fera pas apparaître la paire."""
    a, b = sorted([subject_a_id, subject_b_id])
    with owner_pool() as cur:
        for _ in range(count):
            publication_id = seed_publication(
                "cooc-seed", normalize_title=False, doc_type="article"
            )
            for s in (a, b):
                seed_publication_subject(publication_id, subject_id=s)
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

    def test_search_by_label(self, client):
        label = uniq("FindMeSubject")
        sid = seed_subject(label=label, usage_count=10)
        r = client.get("/api/subjects", params={"search": label.lower()})
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert sid in ids

    def test_min_count_filter(self, client):
        low = seed_subject(uniq("LowCount"), usage_count=1)
        high = seed_subject(uniq("HighCount"), usage_count=50)
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
        label = uniq("DetailSubject")
        sid = seed_subject(label=label, usage_count=5)
        r = client.get(f"/api/subjects/{sid}")
        assert r.status_code == 200
        body = r.json()
        assert body["subject"]["id"] == sid
        assert body["subject"]["label"] == label
        assert body["neighbors"] == []

    def test_returns_neighbors_when_cooccurrences_exist(self, client):
        s_main = seed_subject(uniq("Main"), usage_count=10)
        s_n1 = seed_subject(uniq("Neighbor1"), usage_count=8)
        s_n2 = seed_subject(uniq("Neighbor2"), usage_count=5)
        _seed_cooccurrence(s_main, s_n1, count=10)
        _seed_cooccurrence(s_main, s_n2, count=5)

        r = client.get(f"/api/subjects/{s_main}", params={"min_cooccurrence": 1})
        assert r.status_code == 200
        neighbors = r.json()["neighbors"]
        ids = [n["id"] for n in neighbors]
        assert s_n1 in ids
        assert s_n2 in ids

    def test_min_cooccurrence_filters(self, client):
        s_main = seed_subject(uniq("MainFilter"), usage_count=10)
        s_weak = seed_subject(uniq("WeakNeighbor"), usage_count=8)
        _seed_cooccurrence(s_main, s_weak, count=2)

        r = client.get(f"/api/subjects/{s_main}", params={"min_cooccurrence": 5})
        assert r.status_code == 200
        # Lien de count=2 < min_cooccurrence=5 → filtré.
        ids = [n["id"] for n in r.json()["neighbors"]]
        assert s_weak not in ids

    def test_neighbors_limit_param_validation(self, client):
        # Query(ge=1, le=100) — > 100 = 422.
        s = seed_subject()
        r = client.get(f"/api/subjects/{s}", params={"neighbors_limit": 500})
        assert r.status_code == 422
