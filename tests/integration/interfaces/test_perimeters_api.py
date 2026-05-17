"""Tests d'intégration pour le router `interfaces.api.routers.perimeters`.

Couvre :
- GET /api/perimeters (liste)
- POST /api/perimeters (création, auth)
- PUT /api/perimeters/{id} (update partiel, auth)
- DELETE /api/perimeters/{id} (suppression, auth, refus si utilisé)
- POST /api/perimeters/{id}/structures (ajout d'une racine, auth)
- DELETE /api/perimeters/{id}/structures/{sid} (retrait d'une racine, auth)
"""

from __future__ import annotations

import json
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


def _seed_structure(code: str | None = None, type_: str = "universite") -> int:
    code = code or _uniq("STRUCT")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (%s, %s, CAST(%s AS structure_type)) RETURNING id",
            (code, code, type_),
        )
        return cur.fetchone()["id"]


def _seed_perimeter(code: str | None = None, structure_ids: list[int] | None = None) -> int:
    code = code or _uniq("perim")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES (%s, %s, %s) RETURNING id",
            (code, code, structure_ids or []),
        )
        return cur.fetchone()["id"]


def _set_config(key: str, value: str) -> None:
    """Inscrit une clé de config (utilisée pour bloquer la suppression d'un perimeter)."""
    with _pool() as cur:
        cur.execute(
            "INSERT INTO config (key, value) VALUES (%s, CAST(%s AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, json.dumps(value)),
        )


def _clear_config(key: str) -> None:
    with _pool() as cur:
        cur.execute("DELETE FROM config WHERE key = %s", (key,))


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE perimeters, structures, audit_log, config RESTART IDENTITY CASCADE"
        )


class TestListPerimeters:
    def test_returns_200_with_list(self, client):
        r = client.get("/api/perimeters")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_lists_seeded_perimeter(self, client):
        code = _uniq("listp")
        pid = _seed_perimeter(code=code)
        r = client.get("/api/perimeters")
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert pid in ids


class TestCreatePerimeter:
    def test_requires_admin(self, client):
        r = client.post("/api/perimeters", json={"code": "x", "name": "X"})
        assert r.status_code == 401

    def test_creates_perimeter(self, auth_client):
        code = _uniq("create")
        r = auth_client.post(
            "/api/perimeters",
            json={"code": code, "name": "Created", "description": "desc"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "id" in body
        with _pool() as cur:
            cur.execute(
                "SELECT code, name, description FROM perimeters WHERE id = %s", (body["id"],)
            )
            row = cur.fetchone()
            assert row["code"] == code
            assert row["name"] == "Created"
            assert row["description"] == "desc"

    def test_strips_whitespace_and_empty_description(self, auth_client):
        # `description` vide après strip → None côté repo.
        code = _uniq("strip")
        r = auth_client.post(
            "/api/perimeters",
            json={"code": f"  {code}  ", "name": "  TrimMe  ", "description": "   "},
        )
        assert r.status_code == 200
        with _pool() as cur:
            cur.execute(
                "SELECT code, name, description FROM perimeters WHERE id = %s", (r.json()["id"],)
            )
            row = cur.fetchone()
            assert row["code"] == code
            assert row["name"] == "TrimMe"
            assert row["description"] is None


class TestUpdatePerimeter:
    def test_requires_admin(self, client):
        r = client.put("/api/perimeters/1", json={"name": "X"})
        assert r.status_code == 401

    def test_partial_update_strips_and_clears(self, auth_client):
        pid = _seed_perimeter()
        r = auth_client.put(
            f"/api/perimeters/{pid}",
            json={"name": "  NewName  ", "description": "   "},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        with _pool() as cur:
            cur.execute("SELECT name, description FROM perimeters WHERE id = %s", (pid,))
            row = cur.fetchone()
            assert row["name"] == "NewName"
            assert row["description"] is None

    def test_update_structure_ids(self, auth_client):
        s1 = _seed_structure()
        s2 = _seed_structure()
        pid = _seed_perimeter(structure_ids=[s1])
        r = auth_client.put(f"/api/perimeters/{pid}", json={"structure_ids": [s1, s2]})
        assert r.status_code == 200
        with _pool() as cur:
            cur.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (pid,))
            assert sorted(cur.fetchone()["structure_ids"]) == sorted([s1, s2])


class TestDeletePerimeter:
    def test_requires_admin(self, client):
        r = client.delete("/api/perimeters/1")
        assert r.status_code == 401

    def test_deletes_when_unused(self, auth_client):
        pid = _seed_perimeter()
        r = auth_client.delete(f"/api/perimeters/{pid}")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        with _pool() as cur:
            cur.execute("SELECT 1 FROM perimeters WHERE id = %s", (pid,))
            assert cur.fetchone() is None

    def test_refuses_when_used_in_pipeline_config(self, auth_client):
        # delete_perimeter refuse si une config pipeline référence son code.
        code = _uniq("inuse")
        pid = _seed_perimeter(code=code)
        _set_config("perimeter_persons", code)
        try:
            r = auth_client.delete(f"/api/perimeters/{pid}")
            # 409 Conflict : sémantique correcte ("ressource en usage"), à
            # distinguer de 400 (requête invalide).
            assert r.status_code == 409
        finally:
            _clear_config("perimeter_persons")


class TestAddPerimeterStructure:
    def test_requires_admin(self, client):
        r = client.post("/api/perimeters/1/structures", json={"structure_id": 1})
        assert r.status_code == 401

    def test_adds_new_structure(self, auth_client):
        s = _seed_structure()
        pid = _seed_perimeter()
        r = auth_client.post(f"/api/perimeters/{pid}/structures", json={"structure_id": s})
        assert r.status_code == 200
        assert r.json() == {"status": "added"}
        with _pool() as cur:
            cur.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (pid,))
            assert s in cur.fetchone()["structure_ids"]

    def test_idempotent_already_exists(self, auth_client):
        s = _seed_structure()
        pid = _seed_perimeter(structure_ids=[s])
        r = auth_client.post(f"/api/perimeters/{pid}/structures", json={"structure_id": s})
        assert r.status_code == 200
        assert r.json() == {"status": "already_present"}


class TestRemovePerimeterStructure:
    def test_requires_admin(self, client):
        r = client.delete("/api/perimeters/1/structures/1")
        assert r.status_code == 401

    def test_removes_structure(self, auth_client):
        s1 = _seed_structure()
        s2 = _seed_structure()
        pid = _seed_perimeter(structure_ids=[s1, s2])
        r = auth_client.delete(f"/api/perimeters/{pid}/structures/{s1}")
        assert r.status_code == 200
        assert r.json() == {"status": "removed"}
        with _pool() as cur:
            cur.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (pid,))
            ids = cur.fetchone()["structure_ids"]
            assert s1 not in ids
            assert s2 in ids
