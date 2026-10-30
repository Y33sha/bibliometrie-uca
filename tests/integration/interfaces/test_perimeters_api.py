"""Tests d'intégration pour le router `interfaces.api.routers.perimeters`.

Couvre :
- GET /api/perimeters (liste)
- POST /api/perimeters (création avec ses racines, auth)
- PUT /api/perimeters/{id} (mise à jour partielle, auth)
- DELETE /api/perimeters/{id} (suppression, auth, refus si utilisé)
"""

from __future__ import annotations

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_config,
    seed_perimeter,
    seed_structure,
    seed_tutelle,
    uniq,
)


def _clear_config(key: str) -> None:
    with owner_pool() as cur:
        cur.execute("DELETE FROM config WHERE key = %s", (key,))


class TestListPerimeters:
    def test_returns_200_with_list(self, client):
        r = client.get("/api/perimeters")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_lists_seeded_perimeter(self, client):
        code = uniq("listp")
        pid = seed_perimeter(code=code)
        r = client.get("/api/perimeters")
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert pid in ids

    def test_flags_the_persons_perimeter(self, client):
        persons = seed_perimeter(code=uniq("persons"))
        other = seed_perimeter(code=uniq("other"))
        with owner_pool() as cur:
            cur.execute("SELECT code FROM perimeters WHERE id = %s", (persons,))
            seed_config("perimeter_persons", cur.fetchone()["code"])
        try:
            flags = {p["id"]: p["is_persons"] for p in client.get("/api/perimeters").json()}
        finally:
            _clear_config("perimeter_persons")
        assert flags[persons] is True
        assert flags[other] is False


class TestCreatePerimeter:
    def test_creates_perimeter(self, auth_client):
        code = uniq("create")
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
        code = uniq("strip")
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
        pid = seed_perimeter()
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
        s1 = seed_structure(type_="universite")
        s2 = seed_structure(type_="universite")
        pid = seed_perimeter(root_structure_ids=[s1])
        r = auth_client.put(f"/api/perimeters/{pid}", json={"root_structure_ids": [s1, s2]})
        assert r.status_code == 200
        with owner_pool() as cur:
            cur.execute("SELECT root_structure_ids FROM perimeters WHERE id = %s", (pid,))
            assert sorted(cur.fetchone()["root_structure_ids"]) == sorted([s1, s2])


class TestDeletePerimeter:
    def test_deletes_when_unused(self, auth_client):
        pid = seed_perimeter()
        r = auth_client.delete(f"/api/perimeters/{pid}")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        with owner_pool() as cur:
            cur.execute("SELECT 1 FROM perimeters WHERE id = %s", (pid,))
            assert cur.fetchone() is None

    def test_refuses_when_used_in_pipeline_config(self, auth_client):
        # La configuration du pipeline référence le périmètre.
        code = uniq("inuse")
        pid = seed_perimeter(code=code)
        seed_config("perimeter_persons", code)
        try:
            r = auth_client.delete(f"/api/perimeters/{pid}")
            # Ressource en usage : 409.
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
    """La table `perimeter_structures` (racines et leurs descendants par `est_tutelle_de`) est rafraîchie à chaque écriture de l'administration, sans attendre le pipeline."""

    def test_adding_root_materializes_closure(self, auth_client):
        root = seed_structure(type_="universite")
        lab = seed_structure(type_="labo")
        seed_tutelle(root, child_id=lab)
        pid = seed_perimeter()
        r = auth_client.put(f"/api/perimeters/{pid}", json={"root_structure_ids": [root]})
        assert r.status_code == 200
        assert _perimeter_structure_ids(pid) == {root, lab}

    def test_creating_with_roots_materializes_closure(self, auth_client):
        root = seed_structure(type_="universite")
        lab = seed_structure(type_="labo")
        seed_tutelle(root, child_id=lab)
        code = uniq("withroots")
        r = auth_client.post(
            "/api/perimeters", json={"code": code, "name": code, "root_structure_ids": [root]}
        )
        assert r.status_code == 200
        assert _perimeter_structure_ids(r.json()["id"]) == {root, lab}

    def test_creating_tutelle_relation_materializes_new_descendant(self, auth_client):
        root = seed_structure(type_="universite")
        lab = seed_structure(type_="labo")
        pid = seed_perimeter(root_structure_ids=[root])
        r = auth_client.post(
            "/api/structures/tutelles",
            json={"parent_id": root, "child_id": lab},
        )
        assert r.status_code == 200
        assert _perimeter_structure_ids(pid) == {root, lab}


# ── Traçabilité des écritures sur les périmètres ─────────────


def _audit(event_type: str, entity_id: int) -> list[dict]:
    with owner_pool() as cur:
        cur.execute(
            "SELECT payload, user_id FROM audit_log "
            "WHERE event_type = %s AND entity_id = %s ORDER BY id",
            (event_type, entity_id),
        )
        return cur.fetchall()


class TestTracabilite:
    """La création et la modification d'un périmètre sont consignées : un périmètre décide quelles structures entrent dans les décomptes."""

    def test_la_creation_est_consignee(self, auth_client):
        code = uniq("audit_create")
        racine = seed_structure(type_="universite")
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
        code = uniq("audit_update")
        pid = auth_client.post("/api/perimeters", json={"code": code, "name": "Avant"}).json()["id"]

        r = auth_client.put(f"/api/perimeters/{pid}", json={"name": "Après"})
        assert r.status_code == 200

        evenements = _audit("perimeter.updated", pid)
        assert len(evenements) == 1
        # Une mise à jour partielle consigne seulement les champs reçus.
        assert evenements[0]["payload"] == {"name": "Après"}

    def test_un_changement_de_racines_est_consigne(self, auth_client):
        code = uniq("audit_roots")
        pid = auth_client.post("/api/perimeters", json={"code": code, "name": "Racines"}).json()[
            "id"
        ]
        racine = seed_structure(type_="universite")

        r = auth_client.put(f"/api/perimeters/{pid}", json={"root_structure_ids": [racine]})
        assert r.status_code == 200

        evenements = _audit("perimeter.updated", pid)
        assert len(evenements) == 1
        assert evenements[0]["payload"] == {"root_structure_ids": [racine]}
