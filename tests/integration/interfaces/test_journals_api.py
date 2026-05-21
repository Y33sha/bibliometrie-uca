"""Tests d'intégration pour le router `interfaces.api.routers.journals`.

Couvre :
- GET /api/journals (liste, search, publisher filter, sort variants)
- GET /api/journals/{id} (detail, 404)
- PUT /api/journals/{id} (update, auth requise, 404)
- POST /api/journals/{id}/merge (auth requise, 404 target/source, happy)
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


def _seed_publisher(name: str | None = None) -> int:
    name = name or _uniq("Publisher")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO publishers (name, name_normalized) VALUES (%s, lower(%s)) RETURNING id",
            (name, name),
        )
        return cur.fetchone()["id"]


def _seed_journal(title: str | None = None, publisher_id: int | None = None) -> int:
    title = title or _uniq("Journal")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO journals (title, title_normalized, publisher_id) "
            "VALUES (%s, lower(%s), %s) RETURNING id",
            (title, title, publisher_id),
        )
        return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE journals, publishers, publications, audit_log RESTART IDENTITY CASCADE"
        )


class TestListJournals:
    def test_returns_200_with_paginated_shape(self, client):
        r = client.get("/api/journals")
        assert r.status_code == 200
        body = r.json()
        assert {"total", "page", "pages", "journals"} <= set(body)

    def test_pagination_params(self, client):
        r = client.get("/api/journals", params={"page": 2, "per_page": 5})
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 2

    def test_search_min_length_ignored(self, client):
        # search < 2 caractères : pas de filtre appliqué.
        r = client.get("/api/journals", params={"search": "a"})
        assert r.status_code == 200

    def test_search_applied(self, client):
        title = _uniq("ElsevierJournal")
        _seed_journal(title)
        r = client.get("/api/journals", params={"search": title.lower()})
        assert r.status_code == 200
        assert any(j["title"] == title for j in r.json()["journals"])

    def test_filter_by_publisher(self, client):
        pub = _seed_publisher()
        j = _seed_journal(publisher_id=pub)
        r = client.get("/api/journals", params={"publisher_id": pub})
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["journals"]]
        assert j in ids

    @pytest.mark.parametrize(
        "sort",
        ["title", "-title", "publisher", "-publisher", "pubs", "-pubs", "unknown"],
    )
    def test_sort_variants(self, client, sort):
        # `unknown` doit fallback sur `title` ASC sans 500.
        r = client.get("/api/journals", params={"sort": sort})
        assert r.status_code == 200

    def test_per_page_above_limit_rejected(self, client):
        # `per_page` Query(le=200) → > 200 = 422.
        r = client.get("/api/journals", params={"per_page": 500})
        assert r.status_code == 422


class TestGetJournal:
    def test_404_when_unknown(self, client):
        r = client.get("/api/journals/999999999")
        assert r.status_code == 404

    def test_returns_existing(self, client):
        title = _uniq("DetailJournal")
        jid = _seed_journal(title)
        r = client.get(f"/api/journals/{jid}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == jid
        assert body["title"] == title


class TestUpdateJournal:
    def test_requires_admin(self, client):
        r = client.put("/api/journals/1", json={"title": "X"})
        assert r.status_code == 401

    def test_updates_partial_fields(self, auth_client):
        jid = _seed_journal()
        r = auth_client.put(
            f"/api/journals/{jid}",
            json={
                "title": "UpdatedTitle",
                "is_predatory": True,
                "notes": "Note",
            },
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        # Vérifier en base que seuls les champs envoyés sont écrits.
        with _pool() as cur:
            cur.execute("SELECT title, is_predatory, notes FROM journals WHERE id = %s", (jid,))
            row = cur.fetchone()
            assert row["title"] == "UpdatedTitle"
            assert row["is_predatory"] is True
            assert row["notes"] == "Note"


class TestMergeJournals:
    def test_requires_admin(self, client):
        r = client.post("/api/journals/1/merge", json={"source_id": 2})
        assert r.status_code == 401

    def test_404_when_target_missing(self, auth_client):
        src = _seed_journal()
        r = auth_client.post("/api/journals/999999999/merge", json={"source_id": src})
        assert r.status_code == 404
        assert "cible" in r.json()["detail"]

    def test_404_when_source_missing(self, auth_client):
        dst = _seed_journal()
        r = auth_client.post(f"/api/journals/{dst}/merge", json={"source_id": 999999998})
        assert r.status_code == 404
        assert "source" in r.json()["detail"]

    def test_happy_path(self, auth_client):
        src = _seed_journal("MergeSrc")
        dst = _seed_journal("MergeDst")
        r = auth_client.post(f"/api/journals/{dst}/merge", json={"source_id": src})
        assert r.status_code == 200
        body = r.json()
        assert body == {"merged": True, "source_id": src, "target_id": dst}
        # Source supprimée, target conservée.
        with _pool() as cur:
            cur.execute("SELECT id FROM journals WHERE id IN (%s, %s)", (src, dst))
            ids = {row["id"] for row in cur.fetchall()}
            assert dst in ids
            assert src not in ids


# ── GET /api/journal-types ──────────────────────────────────────


class TestJournalTypes:
    def test_returns_all_values_with_labels(self, client):
        r = client.get("/api/journal-types")
        assert r.status_code == 200
        body = r.json()
        values = [opt["value"] for opt in body]
        assert values == [
            "journal",
            "proceedings",
            "repository",
            "book_series",
            "preprint_server",
            "media",
        ]
        assert all("label_fr" in opt and opt["label_fr"] for opt in body)
