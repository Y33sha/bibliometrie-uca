"""Tests d'intégration pour le router `interfaces.api.routers.perimeters`.

Couvre :
- GET /api/perimeters (liste)
- POST /api/perimeters (création avec ses racines, auth)
- PUT /api/perimeters/{id} (update partiel, auth)
- DELETE /api/perimeters/{id} (suppression, auth, refus si utilisé)
"""

from __future__ import annotations

import json
import uuid

import pytest

from tests.integration.helpers.db import owner_pool


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _seed_structure(code: str | None = None, type_: str = "universite") -> int:
    code = code or _uniq("STRUCT")
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (%s, %s, CAST(%s AS structure_type)) RETURNING id",
            (code, code, type_),
        )
        return cur.fetchone()["id"]


def _seed_perimeter(code: str | None = None, root_structure_ids: list[int] | None = None) -> int:
    code = code or _uniq("perim")
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO perimeters (code, name, root_structure_ids) VALUES (%s, %s, %s) RETURNING id",
            (code, code, root_structure_ids or []),
        )
        return cur.fetchone()["id"]


def _set_config(key: str, value: str) -> None:
    """Inscrit une clé de config (utilisée pour bloquer la suppression d'un perimeter)."""
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO config (key, value) VALUES (%s, CAST(%s AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, json.dumps(value)),
        )


def _clear_config(key: str) -> None:
    with owner_pool() as cur:
        cur.execute("DELETE FROM config WHERE key = %s", (key,))


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with owner_pool() as cur:
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
    def test_creates_perimeter(self, auth_client):
        code = _uniq("create")
        r = auth_client.post(
            "/api/perimeters",
            json={"code": code, "name": "Created"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "id" in body
        with owner_pool() as cur:
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
        with owner_pool() as cur:
            cur.execute("SELECT code, name FROM perimeters WHERE id = %s", (r.json()["id"],))
            row = cur.fetchone()
            assert row["code"] == code
            assert row["name"] == "TrimMe"


class TestUpdatePerimeter:
    def test_partial_update_strips_name(self, auth_client):
        pid = _seed_perimeter()
        r = auth_client.put(
            f"/api/perimeters/{pid}",
            json={"name": "  NewName  "},
        )
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        with owner_pool() as cur:
            cur.execute("SELECT name FROM perimeters WHERE id = %s", (pid,))
            row = cur.fetchone()
            assert row["name"] == "NewName"

    def test_update_structure_ids(self, auth_client):
        s1 = _seed_structure()
        s2 = _seed_structure()
        pid = _seed_perimeter(root_structure_ids=[s1])
        r = auth_client.put(f"/api/perimeters/{pid}", json={"root_structure_ids": [s1, s2]})
        assert r.status_code == 200
        with owner_pool() as cur:
            cur.execute("SELECT root_structure_ids FROM perimeters WHERE id = %s", (pid,))
            assert sorted(cur.fetchone()["root_structure_ids"]) == sorted([s1, s2])


class TestDeletePerimeter:
    def test_deletes_when_unused(self, auth_client):
        pid = _seed_perimeter()
        r = auth_client.delete(f"/api/perimeters/{pid}")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        with owner_pool() as cur:
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
    with owner_pool() as cur:
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
        with owner_pool() as cur:
            cur.execute(
                "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
                "VALUES (%s, %s, 'est_tutelle_de')",
                (root, lab),
            )
        pid = _seed_perimeter()
        r = auth_client.put(f"/api/perimeters/{pid}", json={"root_structure_ids": [root]})
        assert r.status_code == 200
        assert _perimeter_structure_ids(pid) == {root, lab}

    def test_creating_with_roots_materializes_closure(self, auth_client):
        root = _seed_structure()
        lab = _seed_structure(type_="labo")
        with owner_pool() as cur:
            cur.execute(
                "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
                "VALUES (%s, %s, 'est_tutelle_de')",
                (root, lab),
            )
        code = _uniq("withroots")
        r = auth_client.post(
            "/api/perimeters", json={"code": code, "name": code, "root_structure_ids": [root]}
        )
        assert r.status_code == 200
        assert _perimeter_structure_ids(r.json()["id"]) == {root, lab}

    def test_creating_tutelle_relation_materializes_new_descendant(self, auth_client):
        root = _seed_structure()
        lab = _seed_structure(type_="labo")
        pid = _seed_perimeter(root_structure_ids=[root])
        r = auth_client.post(
            "/api/structures/relations",
            json={"parent_id": root, "child_id": lab, "relation_type": "est_tutelle_de"},
        )
        assert r.status_code == 200
        assert _perimeter_structure_ids(pid) == {root, lab}


# ── Traçabilité des écritures sur les périmètres ─────────────


def _audit(event_type: str, aggregate_id: int) -> list[dict]:
    with owner_pool() as cur:
        cur.execute(
            "SELECT payload, user_id FROM audit_log "
            "WHERE event_type = %s AND aggregate_id = %s ORDER BY id",
            (event_type, aggregate_id),
        )
        return cur.fetchall()


class TestTracabilite:
    """La suppression d'un périmètre était consignée, sa création et sa modification non.

    Un périmètre décide quelles structures entrent dans les décomptes : le poser, en changer les racines ou le retirer sont trois décisions de même portée, et la première n'est pas moins traçable que la dernière.
    """

    def test_la_creation_est_consignee(self, auth_client):
        code = _uniq("audit_create")
        racine = _seed_structure()
        r = auth_client.post(
            "/api/perimeters",
            json={"code": code, "name": "Audité", "root_structure_ids": [racine]},
        )
        assert r.status_code == 200
        pid = r.json()["id"]

        evenements = _audit("perimeter.created", pid)
        assert len(evenements) == 1
        assert evenements[0]["payload"] == {
            "code": code,
            "name": "Audité",
            "root_structure_ids": [racine],
        }
        assert evenements[0]["user_id"]

    def test_la_modification_ne_consigne_que_les_champs_fournis(self, auth_client):
        code = _uniq("audit_update")
        pid = auth_client.post("/api/perimeters", json={"code": code, "name": "Avant"}).json()["id"]

        r = auth_client.put(f"/api/perimeters/{pid}", json={"name": "Après"})
        assert r.status_code == 200

        evenements = _audit("perimeter.updated", pid)
        assert len(evenements) == 1
        # Une mise à jour partielle n'écrit que ce qu'elle a reçu : consigner les autres champs
        # laisserait croire qu'ils ont été soumis.
        assert evenements[0]["payload"] == {"name": "Après"}

    def test_un_changement_de_racines_est_consigne(self, auth_client):
        code = _uniq("audit_roots")
        pid = auth_client.post("/api/perimeters", json={"code": code, "name": "Racines"}).json()[
            "id"
        ]
        racine = _seed_structure()

        r = auth_client.put(f"/api/perimeters/{pid}", json={"root_structure_ids": [racine]})
        assert r.status_code == 200

        evenements = _audit("perimeter.updated", pid)
        assert len(evenements) == 1
        assert evenements[0]["payload"] == {"root_structure_ids": [racine]}
