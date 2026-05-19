"""Tests de caractérisation pour le router publishers.

Couvre :
- GET /api/publishers (liste + search + sort variants)
- GET /api/publishers/{id} (detail, 404)
- PUT /api/publishers/{id} (update, auth requise)
- POST /api/publishers/{id}/merge (fusion, auth requise, 404 target/source)
"""

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


def _seed_publisher(name: str | None = None) -> int:
    name = name or _uniq("Publisher")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO publishers (name, name_normalized) VALUES (%s, lower(%s)) RETURNING id",
            (name, name),
        )
        return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE publishers, journals, publications, audit_log RESTART IDENTITY CASCADE"
        )


# ── GET /api/publishers ─────────────────────────────────────────


class TestListPublishers:
    def test_empty_ok(self, client):
        r = client.get("/api/publishers")
        assert r.status_code == 200
        body = r.json()
        assert "total" in body
        assert "publishers" in body

    def test_pagination(self, client):
        r = client.get("/api/publishers", params={"page": 2, "per_page": 10})
        assert r.status_code == 200

    def test_search_min_length(self, client):
        # search < 2 caractères → ignoré (pas de filtre appliqué)
        r = client.get("/api/publishers", params={"search": "a"})
        assert r.status_code == 200

    def test_search_applied(self, client):
        name = _uniq("Elsevier")
        _seed_publisher(name)
        r = client.get("/api/publishers", params={"search": name.lower()})
        assert r.status_code == 200
        assert any(p["name"] == name for p in r.json()["publishers"])

    def test_doi_prefixes_aggregated(self, client):
        """Les préfixes DOI rattachés à un éditeur sont remontés via JOIN sur doi_prefixes."""
        name = _uniq("PrefixedPub")
        pid = _seed_publisher(name)
        with _pool() as cur:
            cur.execute(
                "INSERT INTO doi_prefixes (prefix, ra, publisher_id, crossref_member_id) "
                "VALUES (%s, %s, %s, %s), (%s, %s, %s, %s)",
                ("10.aaaa", "Crossref", pid, 42, "10.bbbb", "Crossref", pid, 42),
            )
        r = client.get("/api/publishers", params={"search": name.lower()})
        assert r.status_code == 200
        pub = next(p for p in r.json()["publishers"] if p["id"] == pid)
        prefixes = {p["prefix"] for p in pub["doi_prefixes"]}
        assert prefixes == {"10.aaaa", "10.bbbb"}
        assert all(p["ra"] == "Crossref" for p in pub["doi_prefixes"])
        assert all(p["crossref_member_id"] == 42 for p in pub["doi_prefixes"])

    def test_sort_name_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "-name"})
        assert r.status_code == 200

    def test_sort_journals(self, client):
        r = client.get("/api/publishers", params={"sort": "journals"})
        assert r.status_code == 200

    def test_sort_journals_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "-journals"})
        assert r.status_code == 200

    def test_sort_pubs(self, client):
        r = client.get("/api/publishers", params={"sort": "pubs"})
        assert r.status_code == 200

    def test_sort_pubs_desc(self, client):
        r = client.get("/api/publishers", params={"sort": "-pubs"})
        assert r.status_code == 200

    def test_sort_unknown_fallback(self, client):
        # Sort inconnu → fallback sur name ASC
        r = client.get("/api/publishers", params={"sort": "unknown"})
        assert r.status_code == 200


# ── GET /api/publishers/{id} ────────────────────────────────────


class TestGetPublisher:
    def test_404(self, client):
        r = client.get("/api/publishers/999999999")
        assert r.status_code == 404

    def test_ok(self, client):
        pid = _seed_publisher("TestGetPub")
        r = client.get(f"/api/publishers/{pid}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == pid
        assert body["name"] == "TestGetPub"


# ── PUT /api/publishers/{id} ────────────────────────────────────


class TestUpdatePublisher:
    def test_requires_admin(self, client):
        r = client.put("/api/publishers/1", json={"name": "Updated"})
        assert r.status_code == 401

    def test_ok(self, auth_client):
        pid = _seed_publisher()
        r = auth_client.put(
            f"/api/publishers/{pid}",
            json={
                "name": "UpdatedName",
                "country": "FR",
                "is_predatory": False,
                "notes": "Note",
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ── POST /api/publishers/{id}/merge ─────────────────────────────


class TestMergePublishers:
    def test_requires_admin(self, client):
        r = client.post("/api/publishers/1/merge", json={"source_id": 2})
        assert r.status_code == 401

    def test_target_not_found(self, auth_client):
        src = _seed_publisher()
        r = auth_client.post("/api/publishers/999999999/merge", json={"source_id": src})
        assert r.status_code == 404

    def test_source_not_found(self, auth_client):
        dst = _seed_publisher()
        r = auth_client.post(f"/api/publishers/{dst}/merge", json={"source_id": 999999998})
        assert r.status_code == 404

    def test_ok(self, auth_client):
        src = _seed_publisher("MergeSrc")
        dst = _seed_publisher("MergeDst")
        r = auth_client.post(f"/api/publishers/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200
        body = r.json()
        assert body["merged"] is True
        assert body["source_id"] == src
        assert body["target_id"] == dst
