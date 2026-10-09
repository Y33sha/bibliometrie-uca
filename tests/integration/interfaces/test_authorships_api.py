"""Tests de caractérisation pour le router `admin/authorships`.

Couvre :
- PATCH /api/authorships/{id}/exclude
- GET / POST /api/authorships/orphans/*

Stratégie : seed minimal via un pool dédié (hors pool API), ids uniques par
test pour éviter les collisions.
"""

import uuid

from tests.integration.helpers.db import owner_pool, truncate_after_module
from tests.integration.helpers.seeds import (
    seed_authorship,
    seed_person,
    seed_publication,
    seed_rejected_authorship,
    seed_source_authorship,
    seed_source_publication,
    uniq,
)


def _uniq_name(prefix: str) -> str:
    """Nom de personne unique, en lettres seules : le nettoyage des noms bruts retire les chiffres."""
    return prefix + uuid.uuid4().hex[:8].translate(str.maketrans("0123456789", "ghijklmnop"))


_cleanup_after_module = truncate_after_module(
    "authorships",
    "source_authorships",
    "author_identifying_keys",
    "source_publications",
    "publications",
    "persons",
    "audit_log",
)


def _seed_orphan_with_pub(raw_author_name: str = "Reject Me") -> tuple[int, int]:
    """source_authorship orpheline (person_id NULL, in_perimeter TRUE) rattachée à une publication.

    Renvoie (sa_id, publication_id) pour pouvoir rejeter la paire."""
    pub_id = seed_publication(title=uniq("Pub"))
    sp_id = seed_source_publication(publication_id=pub_id)
    sa_id = seed_source_authorship(
        source="hal", source_pub_id=sp_id, raw_author_name=raw_author_name
    )
    return sa_id, pub_id


# ── PATCH /api/authorships/{id}/exclude ─────────────────────────


class TestExcludeAuthorship:
    def test_ok(self, auth_client):
        pid = seed_person()
        pub = seed_publication("Exclude test")
        aid = seed_authorship(pub, person_id=pid, in_perimeter=True)
        r = auth_client.patch(f"/api/authorships/{aid}/exclude")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ── Orphan authorships ──────────────────────────────────────────


class TestOrphanAuthorships:
    def test_count(self, client):
        r = client.get("/api/authorships/orphans/count")
        assert r.status_code == 200

    def test_list(self, client):
        r = client.get("/api/authorships/orphans", params={"page": 1, "per_page": 50})
        assert r.status_code == 200

    def test_list_with_search(self, client):
        r = client.get("/api/authorships/orphans", params={"search": "foo"})
        assert r.status_code == 200

    def test_list_and_facets_with_lab_filter(self, client):
        for path in ("/api/authorships/orphans", "/api/authorships/orphans/facets"):
            r = client.get(path, params={"lab_id": "1,none"})
            assert r.status_code == 200, path

    def test_malformed_lab_id_is_422(self, client):
        r = client.get("/api/authorships/orphans", params={"lab_id": "abc"})
        assert r.status_code == 422

    def test_returns_last_name_first_name_from_comma_form(self, client):
        """Format "Last, First" : parsé en last_name="Last", first_name="First"."""
        marker = _uniq_name("Marker")
        _seed_orphan_with_pub(f"{marker}, Jane")

        r = client.get("/api/authorships/orphans", params={"search": marker})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        item = body["authorships"][0]
        assert item["last_name"] == marker
        assert item["first_name"] == "Jane"
        assert item["full_name"] == f"{marker}, Jane"

    def test_returns_last_name_first_name_from_space_form(self, client):
        """Format "First Last" : parsé en last_name=dernier mot, first_name=reste."""
        marker = _uniq_name("Marker")
        _seed_orphan_with_pub(f"Jane Marie {marker}")

        r = client.get("/api/authorships/orphans", params={"search": marker})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        item = body["authorships"][0]
        assert item["last_name"] == marker
        assert item["first_name"] == "Jane Marie"


class TestAssignOrphanAuthorship:
    def test_missing_person_id_and_create(self, auth_client):
        sa = seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/authorships/orphans/assign",
            json={"source_authorship_id": sa},
        )
        assert r.status_code == 422

    def test_create_person_empty_name(self, auth_client):
        sa = seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/authorships/orphans/assign",
            json={
                "source_authorship_id": sa,
                "create_person": {"last_name": "   ", "first_name": "X"},
            },
        )
        assert r.status_code == 422

    def test_person_not_found(self, auth_client):
        sa = seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/authorships/orphans/assign",
            json={"source_authorship_id": sa, "person_id": 999999999},
        )
        assert r.status_code == 404

    def test_ok_with_person_id(self, auth_client):
        pid = seed_person()
        sa = seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/authorships/orphans/assign",
            json={"source_authorship_id": sa, "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["person_id"] == pid

    def test_assign_visible_immediately(self, auth_client):
        # Régression (chantier commit-avant-réponse) : le command handler commit
        # avant l'envoi de la réponse, donc le rattachement est lisible depuis une
        # connexion indépendante. Garde-fou du passage final du teardown de
        # db_conn en rollback — un handler sans `commit()` ferait échouer ce test.
        pid = seed_person()
        sa = seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/authorships/orphans/assign",
            json={"source_authorship_id": sa, "person_id": pid},
        )
        assert r.status_code == 200
        with owner_pool() as cur:
            cur.execute("SELECT person_id FROM source_authorships WHERE id = %s", (sa,))
            assert cur.fetchone()["person_id"] == pid

    def test_ok_with_create_person(self, auth_client):
        sa = seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/authorships/orphans/assign",
            json={
                "source_authorship_id": sa,
                "create_person": {"last_name": "Créée", "first_name": "Ici"},
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_blocked_when_pair_rejected(self, auth_client):
        pid = seed_person()
        sa, pub = _seed_orphan_with_pub()
        seed_rejected_authorship(pub, person_id=pid)
        r = auth_client.post(
            "/api/authorships/orphans/assign",
            json={"source_authorship_id": sa, "person_id": pid},
        )
        assert r.status_code == 409
        pair = r.json()["rejected_pairs"][0]
        assert pair["publication_id"] == pub
        assert pair["person_id"] == pid
        assert pair["rejected_at"]

    def test_forced_unrejects_and_assigns(self, auth_client):
        pid = seed_person()
        sa, pub = _seed_orphan_with_pub()
        seed_rejected_authorship(pub, person_id=pid)
        r = auth_client.post(
            "/api/authorships/orphans/assign",
            json={"source_authorship_id": sa, "person_id": pid, "force": True},
        )
        assert r.status_code == 200
        assert r.json()["person_id"] == pid


class TestBatchAssignOrphanAuthorships:
    def test_empty_authorships_ok_zero(self, auth_client):
        pid = seed_person()
        r = auth_client.post(
            "/api/authorships/orphans/batch-assign",
            json={"source_authorship_ids": [], "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 0

    def test_person_not_found(self, auth_client):
        sa = seed_source_authorship(source="hal")
        r = auth_client.post(
            "/api/authorships/orphans/batch-assign",
            json={"source_authorship_ids": [sa], "person_id": 999999999},
        )
        assert r.status_code == 404

    def test_ok(self, auth_client):
        pid = seed_person()
        sa1 = seed_source_authorship(source="hal")
        sa2 = seed_source_authorship(source="openalex")
        r = auth_client.post(
            "/api/authorships/orphans/batch-assign",
            json={"source_authorship_ids": [sa1, sa2], "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] >= 0

    def test_blocked_when_pair_rejected(self, auth_client):
        pid = seed_person()
        sa, pub = _seed_orphan_with_pub()
        seed_rejected_authorship(pub, person_id=pid)
        r = auth_client.post(
            "/api/authorships/orphans/batch-assign",
            json={"source_authorship_ids": [sa], "person_id": pid},
        )
        assert r.status_code == 409
        assert r.json()["rejected_pairs"][0]["publication_id"] == pub

    def test_forced_unrejects_and_assigns(self, auth_client):
        pid = seed_person()
        sa, pub = _seed_orphan_with_pub()
        seed_rejected_authorship(pub, person_id=pid)
        r = auth_client.post(
            "/api/authorships/orphans/batch-assign",
            json={"source_authorship_ids": [sa], "person_id": pid, "force": True},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 1
