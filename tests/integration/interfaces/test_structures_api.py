"""Tests de caractérisation pour le router structures.

Couvre :
- GET /api/structures (list + filtres)
- GET /api/structures/{id} (detail, 404)
- POST/PUT/DELETE /api/structures (mutations, auth requise)
- POST/DELETE /api/structures/relations (relations, auth requise)
- GET/POST/PUT/DELETE /api/name-forms (formes de noms, auth requise)
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


def _seed_structure(code: str | None = None, type_: str = "labo") -> int:
    code = code or _uniq("STR")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (%s, %s, %s::structure_type) RETURNING id",
            (code, code, type_),
        )
        return cur.fetchone()["id"]


def _seed_relation(parent_id: int, child_id: int, rel_type: str = "tutelle") -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
            "VALUES (%s, %s, %s) RETURNING id",
            (parent_id, child_id, rel_type),
        )
        return cur.fetchone()["id"]


def _seed_name_form(structure_id: int, form_text: str | None = None) -> int:
    form_text = form_text or _uniq("form")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary) "
            "VALUES (%s, %s, char_length(%s) <= 6) RETURNING id",
            (structure_id, form_text, form_text),
        )
        return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE structure_name_forms, structure_relations, structures, "
            "audit_log RESTART IDENTITY CASCADE"
        )


# ── GET /api/structures (list) ──────────────────────────────────


class TestListStructures:
    def test_empty_ok(self, client):
        r = client.get("/api/structures")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_filter_by_type(self, client):
        _seed_structure(type_="labo")
        r = client.get("/api/structures", params={"type": "labo"})
        assert r.status_code == 200
        assert all(s["type"] == "labo" for s in r.json())

    def test_filter_by_search(self, client):
        code = _uniq("FINDME")
        _seed_structure(code=code)
        r = client.get("/api/structures", params={"search": code})
        assert r.status_code == 200
        assert any(s["code"] == code for s in r.json())

    def test_combined_filters(self, client):
        r = client.get("/api/structures", params={"type": "labo", "search": "abc"})
        assert r.status_code == 200


# ── GET /api/structures/{id} ────────────────────────────────────


class TestGetStructure:
    def test_404(self, client):
        r = client.get("/api/structures/999999999")
        assert r.status_code == 404

    def test_ok_minimal(self, client):
        sid = _seed_structure()
        r = client.get(f"/api/structures/{sid}")
        assert r.status_code == 200
        body = r.json()
        assert body["structure"]["id"] == sid
        assert body["parents"] == []
        assert body["children"] == []
        assert body["forms"] == []

    def test_ok_with_relations_and_forms(self, client):
        parent = _seed_structure(type_="universite")
        child = _seed_structure(type_="labo")
        _seed_relation(parent, child)
        _seed_name_form(child, _uniq("FormA"))
        _seed_name_form(child, _uniq("FormB"))

        r = client.get(f"/api/structures/{child}")
        assert r.status_code == 200
        body = r.json()
        assert len(body["parents"]) == 1
        assert body["parents"][0]["id"] == parent
        assert len(body["forms"]) == 2

        r2 = client.get(f"/api/structures/{parent}")
        assert r2.status_code == 200
        assert len(r2.json()["children"]) == 1


# ── POST/PUT/DELETE /api/structures ─────────────────────────────


class TestCreateStructure:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/structures",
            json={"code": "X", "name": "X", "type": "labo"},
        )
        assert r.status_code == 401

    def test_ok(self, auth_client):
        code = _uniq("CREATE")
        r = auth_client.post(
            "/api/structures",
            json={
                "code": code,
                "name": "Nouvelle",
                "type": "labo",
                "acronym": "NOV",
                "ror_id": "02scfj030",
                "rnsr_id": None,
                "hal_collection": "COLL",
                "api_ids": {"openalex": "I1"},
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == code
        assert body["type"] == "labo"

    def test_create_visible_immediately(self, auth_client):
        # Régression (chantier commit-avant-réponse) : la structure écrite par le POST
        # est commitée avant l'envoi de la réponse, donc lisible depuis une connexion
        # indépendante. Garde-fou du passage final du teardown de db_conn en
        # rollback — un command handler sans `commit()` ferait alors échouer ce test.
        code = _uniq("READBACK")
        r = auth_client.post(
            "/api/structures",
            json={"code": code, "name": "Readback", "type": "labo"},
        )
        assert r.status_code == 200
        with _pool() as cur:
            cur.execute("SELECT id FROM structures WHERE code = %s", (code,))
            assert cur.fetchone() is not None


class TestUpdateStructure:
    def test_requires_admin(self, client):
        r = client.put("/api/structures/1", json={"name": "Y"})
        assert r.status_code == 401

    def test_404(self, auth_client):
        r = auth_client.put("/api/structures/999999999", json={"name": "Z"})
        assert r.status_code == 404

    def test_ok(self, auth_client):
        sid = _seed_structure()
        r = auth_client.put(
            f"/api/structures/{sid}",
            json={"name": "Renommée", "acronym": "REN"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Renommée"


class TestDeleteStructure:
    def test_requires_admin(self, client):
        r = client.delete("/api/structures/1")
        assert r.status_code == 401

    def test_404(self, auth_client):
        r = auth_client.delete("/api/structures/999999999")
        assert r.status_code == 404

    def test_ok(self, auth_client):
        sid = _seed_structure()
        r = auth_client.delete(f"/api/structures/{sid}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True


# ── structure-relations ─────────────────────────────────────────


class TestCreateRelation:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/structures/relations",
            json={"parent_id": 1, "child_id": 2, "relation_type": "tutelle"},
        )
        assert r.status_code == 401

    def test_ok(self, auth_client):
        parent = _seed_structure(type_="universite")
        child = _seed_structure(type_="labo")
        r = auth_client.post(
            "/api/structures/relations",
            json={
                "parent_id": parent,
                "child_id": child,
                "relation_type": "tutelle",
            },
        )
        assert r.status_code == 200
        body = r.json()
        # Peut renvoyer la ligne ou {"status": "already_exists"}
        assert "status" in body or "id" in body or "relation_id" in body

    def test_duplicate_already_exists(self, auth_client):
        parent = _seed_structure(type_="universite")
        child = _seed_structure(type_="labo")
        _seed_relation(parent, child, "tutelle")
        r = auth_client.post(
            "/api/structures/relations",
            json={
                "parent_id": parent,
                "child_id": child,
                "relation_type": "tutelle",
            },
        )
        assert r.status_code == 200
        assert r.json().get("status") == "already_exists"


class TestDeleteRelation:
    def test_requires_admin(self, client):
        r = client.delete("/api/structures/relations/1")
        assert r.status_code == 401

    def test_404(self, auth_client):
        r = auth_client.delete("/api/structures/relations/999999999")
        assert r.status_code == 404

    def test_ok(self, auth_client):
        parent = _seed_structure(type_="universite")
        child = _seed_structure(type_="labo")
        rid = _seed_relation(parent, child)
        r = auth_client.delete(f"/api/structures/relations/{rid}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True


# ── name-forms ──────────────────────────────────────────────────


class TestGetNameForm:
    def test_404(self, client):
        r = client.get("/api/name-forms/999999999")
        assert r.status_code == 404

    def test_ok(self, client):
        sid = _seed_structure()
        fid = _seed_name_form(sid)
        r = client.get(f"/api/name-forms/{fid}")
        assert r.status_code == 200
        assert r.json()["id"] == fid


class TestCreateNameForm:
    def test_requires_admin(self, client):
        r = client.post("/api/name-forms", json={"structure_id": 1, "form_text": "X"})
        assert r.status_code == 401

    def test_ok(self, auth_client):
        sid = _seed_structure()
        r = auth_client.post(
            "/api/name-forms",
            json={
                "structure_id": sid,
                "form_text": _uniq("F"),
                "is_word_boundary": True,
                "is_excluding": False,
            },
        )
        assert r.status_code == 200
        assert "id" in r.json()

    def test_with_requires_context(self, auth_client):
        sid = _seed_structure()
        ctx = _seed_structure()
        r = auth_client.post(
            "/api/name-forms",
            json={
                "structure_id": sid,
                "form_text": _uniq("Fctx"),
                "requires_context_of": [ctx],
            },
        )
        assert r.status_code == 200


class TestUpdateNameForm:
    def test_requires_admin(self, client):
        r = client.put("/api/name-forms/1", json={"form_text": "Y"})
        assert r.status_code == 401

    def test_404(self, auth_client):
        r = auth_client.put("/api/name-forms/999999999", json={"form_text": "Z"})
        assert r.status_code == 404

    def test_ok(self, auth_client):
        sid = _seed_structure()
        fid = _seed_name_form(sid)
        r = auth_client.put(
            f"/api/name-forms/{fid}",
            json={"form_text": _uniq("UpF"), "is_excluding": True},
        )
        assert r.status_code == 200


class TestDeleteNameForm:
    def test_requires_admin(self, client):
        r = client.delete("/api/name-forms/1")
        assert r.status_code == 401

    def test_404(self, auth_client):
        r = auth_client.delete("/api/name-forms/999999999")
        assert r.status_code == 404

    def test_ok(self, auth_client):
        sid = _seed_structure()
        fid = _seed_name_form(sid)
        r = auth_client.delete(f"/api/name-forms/{fid}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True
