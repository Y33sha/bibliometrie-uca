"""Tests d'intégration pour le router `interfaces.api.routers.admin_duplicates`.

Couvre :
- GET /api/admin/duplicates/next (pair candidate ou null)
- POST /api/admin/duplicates/merge (validation, 404, happy path)
- POST /api/admin/duplicates/mark-distinct (validation, happy path)
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


def _seed_publication(
    title: str | None = None,
    doc_type: str = "article",
    pub_year: int = 2024,
    *,
    with_source: bool = False,
) -> int:
    """Insère une publi minimale ; retourne son id.

    `with_source=True` lui rattache une `source_publication` : indispensable dès
    qu'un `refresh_from_sources` est déclenché en aval (une publi sans aucune
    source est supprimée comme orpheline).
    """
    title = title or _uniq("Publi")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO publications (title, title_normalized, doc_type, pub_year) "
            "VALUES (%s, lower(%s), CAST(%s AS doc_type), %s) RETURNING id",
            (title, title, doc_type, pub_year),
        )
        pub_id = cur.fetchone()["id"]
        if with_source:
            cur.execute(
                "INSERT INTO source_publications (source, source_id, title, publication_id) "
                "VALUES ('hal', %s, %s, %s)",
                (_uniq("sp"), title, pub_id),
            )
        return pub_id


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE publications, source_publications, distinct_publications, audit_log "
            "RESTART IDENTITY CASCADE"
        )


class TestNextDuplicateCandidate:
    def test_returns_total_and_pair_shape(self, client):
        # Sur une DB sans paires candidates → total=0, pair=None.
        r = client.get("/api/admin/duplicates/next")
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "offset" in body
        assert "pair" in body  # peut être None

    def test_min_title_len_below_minimum_rejected(self, client):
        # Query param `min_title_len` est `Query(30, ge=10)` → < 10 = 422.
        r = client.get("/api/admin/duplicates/next", params={"min_title_len": 5})
        assert r.status_code == 422

    def test_negative_offset_rejected(self, client):
        r = client.get("/api/admin/duplicates/next", params={"offset": -1})
        assert r.status_code == 422

    def test_offset_zero_default(self, client):
        r = client.get("/api/admin/duplicates/next", params={"offset": 0})
        assert r.status_code == 200
        assert r.json()["offset"] == 0


class TestMergeDuplicatePublications:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/admin/duplicates/merge",
            json={"pub_id_a": 1, "pub_id_b": 2},
        )
        assert r.status_code == 401

    def test_rejects_same_ids(self, auth_client):
        r = auth_client.post(
            "/api/admin/duplicates/merge",
            json={"pub_id_a": 1, "pub_id_b": 1},
        )
        assert r.status_code == 400
        assert "différents" in r.json()["detail"]

    def test_404_when_both_missing(self, auth_client):
        r = auth_client.post(
            "/api/admin/duplicates/merge",
            json={"pub_id_a": 999_999_001, "pub_id_b": 999_999_002},
        )
        assert r.status_code == 404

    def test_404_when_only_one_missing(self, auth_client):
        existing = _seed_publication()
        r = auth_client.post(
            "/api/admin/duplicates/merge",
            json={"pub_id_a": existing, "pub_id_b": 999_999_999},
        )
        assert r.status_code == 404

    def test_merges_two_publications(self, auth_client):
        # Chaque publi porte une source : sinon `refresh_from_sources` (déclenché
        # après la fusion) supprimerait la survivante comme orpheline.
        a = _seed_publication("First publication for merge", with_source=True)
        b = _seed_publication("Second publication for merge", with_source=True)
        r = auth_client.post(
            "/api/admin/duplicates/merge",
            json={"pub_id_a": a, "pub_id_b": b},
        )
        assert r.status_code == 200
        # La cible survivante est le plus petit id (direction implicite).
        survivor, absorbed = sorted((a, b))
        assert r.json() == {"ok": True, "target_id": survivor, "source_id": absorbed}
        with _pool() as cur:
            cur.execute("SELECT id FROM publications WHERE id IN (%s, %s)", (a, b))
            ids = {row["id"] for row in cur.fetchall()}
            assert survivor in ids
            assert absorbed not in ids


class TestMarkDistinctPublications:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/admin/duplicates/mark-distinct",
            json={"pub_id_a": 1, "pub_id_b": 2},
        )
        assert r.status_code == 401

    def test_rejects_same_ids(self, auth_client):
        r = auth_client.post(
            "/api/admin/duplicates/mark-distinct",
            json={"pub_id_a": 1, "pub_id_b": 1},
        )
        assert r.status_code == 400
        assert "différents" in r.json()["detail"]

    def test_marks_pair_distinct(self, auth_client):
        a = _seed_publication("Pub A distinct")
        b = _seed_publication("Pub B distinct")
        r = auth_client.post(
            "/api/admin/duplicates/mark-distinct",
            json={"pub_id_a": a, "pub_id_b": b},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # Vérifier que la paire est persistée dans distinct_publications
        # (les ids sont normalisés en ordre min/max par le port).
        with _pool() as cur:
            cur.execute(
                "SELECT 1 FROM distinct_publications WHERE pub_id_a = %s AND pub_id_b = %s",
                (min(a, b), max(a, b)),
            )
            assert cur.fetchone() is not None
