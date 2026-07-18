"""Tests d'intégration pour le router `interfaces.api.routers.perimeters`.

Couvre :
- GET /api/perimeters (liste)
- POST /api/perimeters (création avec ses racines, auth)
- PUT /api/perimeters/{id} (update partiel, auth)
- DELETE /api/perimeters/{id} (suppression, auth, refus si utilisé)
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
            json={"code": code, "name": "Created"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "id" in body
        with _pool() as cur:
            cur.execute("SELECT code, name FROM perimeters WHERE id = %s", (body["id"],))
            row = cur.fetchone()
            assert row["code"] == code
            assert row["name"] == "Created"

    def test_strips_whitespace(self, auth_client):
        code = _uniq("strip")
        r = auth_client.post(
            "/api/perimeters",
            json={"code": f"  {code}  ", "name": "  TrimMe  "},
        )
        assert r.status_code == 200
        with _pool() as cur:
            cur.execute("SELECT code, name FROM perimeters WHERE id = %s", (r.json()["id"],))
            row = cur.fetchone()
            assert row["code"] == code
            assert row["name"] == "TrimMe"


class TestUpdatePerimeter:
    def test_requires_admin(self, client):
        r = client.put("/api/perimeters/1", json={"name": "X"})
        assert r.status_code == 401

    def test_partial_update_strips_name(self, auth_client):
        pid = _seed_perimeter()
        r = auth_client.put(
            f"/api/perimeters/{pid}",
            json={"name": "  NewName  "},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        with _pool() as cur:
            cur.execute("SELECT name FROM perimeters WHERE id = %s", (pid,))
            row = cur.fetchone()
            assert row["name"] == "NewName"

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


def _perimeter_structure_ids(perimeter_id: int) -> set[int]:
    with _pool() as cur:
        cur.execute(
            "SELECT structure_id FROM perimeter_structures WHERE perimeter_id = %s",
            (perimeter_id,),
        )
        return {row["structure_id"] for row in cur.fetchall()}


class TestMaterializedPerimeterStructures:
    """La table matérialisée `perimeter_structures` est rafraîchie à chaque édition admin,
    sans attendre le pipeline (racine + descendants `est_tutelle_de`)."""

    def test_adding_root_materializes_closure(self, auth_client):
        root = _seed_structure()
        lab = _seed_structure(type_="labo")
        with _pool() as cur:
            cur.execute(
                "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
                "VALUES (%s, %s, 'est_tutelle_de')",
                (root, lab),
            )
        pid = _seed_perimeter()
        r = auth_client.put(f"/api/perimeters/{pid}", json={"structure_ids": [root]})
        assert r.status_code == 200
        assert _perimeter_structure_ids(pid) == {root, lab}

    def test_creating_with_roots_materializes_closure(self, auth_client):
        root = _seed_structure()
        lab = _seed_structure(type_="labo")
        with _pool() as cur:
            cur.execute(
                "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
                "VALUES (%s, %s, 'est_tutelle_de')",
                (root, lab),
            )
        code = _uniq("withroots")
        r = auth_client.post(
            "/api/perimeters", json={"code": code, "name": code, "structure_ids": [root]}
        )
        assert r.status_code == 200
        assert _perimeter_structure_ids(r.json()["id"]) == {root, lab}

    def test_creating_tutelle_relation_materializes_new_descendant(self, auth_client):
        root = _seed_structure()
        lab = _seed_structure(type_="labo")
        pid = _seed_perimeter(structure_ids=[root])
        r = auth_client.post(
            "/api/structure-relations",
            json={"parent_id": root, "child_id": lab, "relation_type": "est_tutelle_de"},
        )
        assert r.status_code == 200
        assert _perimeter_structure_ids(pid) == {root, lab}
