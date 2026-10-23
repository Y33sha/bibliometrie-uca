"""Tests de caractérisation pour le router `admin/contributions`.

Couvre :
- PATCH /api/contributions/{id}/exclude
- GET / POST /api/contributions/orphans/*

Stratégie : seed minimal via un pool dédié (hors pool API), ids uniques par
test pour éviter les collisions.
"""

import uuid

from tests.integration.helpers.db import owner_pool, truncate_after_module
from tests.integration.helpers.seeds import (
    seed_contribution,
    seed_group,
    seed_person,
    seed_publication,
    seed_rejected_contribution,
    seed_source_contribution,
    seed_source_record,
    uniq,
)


def _uniq_name(prefix: str) -> str:
    """Nom de personne unique, en lettres seules : le nettoyage des noms bruts retire les chiffres."""
    return prefix + uuid.uuid4().hex[:8].translate(str.maketrans("0123456789", "ghijklmnop"))


_cleanup_after_module = truncate_after_module(
    "contributions",
    "source_contributions",
    "contributor_information",
    "source_records",
    "publications",
    "persons",
    "audit_log",
)


def _seed_orphan_with_publication(raw_author_name: str = "Reject Me") -> tuple[int, int]:
    """source_contribution orpheline (person_id NULL, in_perimeter TRUE, groupe à elle seule) rattachée à une publication.

    Renvoie (source_contribution_id, publication_id) pour pouvoir rejeter la paire."""
    publication_id = seed_publication(title=uniq("Pub"))
    source_record_id = seed_source_record(publication_id=publication_id)
    source_contribution_id = seed_source_contribution(
        source="hal", source_record_id=source_record_id, raw_author_name=raw_author_name
    )
    seed_group(publication_id, [(source_contribution_id, source_record_id)])
    return source_contribution_id, publication_id


# ── PATCH /api/contributions/{id}/exclude ─────────────────────────


class TestExcludeContribution:
    def test_ok(self, auth_client):
        pid = seed_person()
        publication = seed_publication("Exclude test")
        aid = seed_contribution(publication, person_id=pid, in_perimeter=True)
        r = auth_client.patch(f"/api/contributions/{aid}/exclude")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ── Orphan contributions ──────────────────────────────────────────


class TestOrphanContributions:
    def test_count(self, client):
        r = client.get("/api/contributions/orphans/count")
        assert r.status_code == 200

    def test_list(self, client):
        r = client.get("/api/contributions/orphans", params={"page": 1, "per_page": 50})
        assert r.status_code == 200

    def test_list_with_search(self, client):
        r = client.get("/api/contributions/orphans", params={"search": "foo"})
        assert r.status_code == 200

    def test_list_and_facets_with_lab_filter(self, client):
        for path in ("/api/contributions/orphans", "/api/contributions/orphans/facets"):
            r = client.get(path, params={"lab_id": "1,none"})
            assert r.status_code == 200, path

    def test_malformed_lab_id_is_422(self, client):
        r = client.get("/api/contributions/orphans", params={"lab_id": "abc"})
        assert r.status_code == 422

    def test_returns_last_name_first_name_from_comma_form(self, client):
        """Format "Last, First" : parsé en last_name="Last", first_name="First"."""
        marker = _uniq_name("Marker")
        _seed_orphan_with_publication(f"{marker}, Jane")

        r = client.get("/api/contributions/orphans", params={"search": marker})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        item = body["contributions"][0]
        assert item["last_name"] == marker
        assert item["first_name"] == "Jane"
        assert item["full_name"] == f"{marker}, Jane"

    def test_returns_last_name_first_name_from_space_form(self, client):
        """Format "First Last" : parsé en last_name=dernier mot, first_name=reste."""
        marker = _uniq_name("Marker")
        _seed_orphan_with_publication(f"Jane Marie {marker}")

        r = client.get("/api/contributions/orphans", params={"search": marker})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        item = body["contributions"][0]
        assert item["last_name"] == marker
        assert item["first_name"] == "Jane Marie"


class TestAssignOrphanContribution:
    def test_missing_person_id_and_create(self, auth_client):
        sa = seed_source_contribution(source="hal")
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"source_contribution_id": sa},
        )
        assert r.status_code == 422

    def test_create_person_empty_name(self, auth_client):
        sa = seed_source_contribution(source="hal")
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={
                "source_contribution_id": sa,
                "create_person": {"last_name": "   ", "first_name": "X"},
            },
        )
        assert r.status_code == 422

    def test_person_not_found(self, auth_client):
        sa = seed_source_contribution(source="hal")
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"source_contribution_id": sa, "person_id": 999999999},
        )
        assert r.status_code == 404

    def test_ok_with_person_id(self, auth_client):
        pid = seed_person()
        sa = seed_source_contribution(source="hal")
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"source_contribution_id": sa, "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["person_id"] == pid

    def test_assign_visible_immediately(self, auth_client):
        # Régression (chantier commit-avant-réponse) : le command handler commit
        # avant l'envoi de la réponse, donc le rattachement est lisible depuis une
        # connexion indépendante. Garde-fou du passage final du teardown de
        # db_conn en rollback — un handler sans `commit()` ferait échouer ce test.
        pid = seed_person()
        sa = seed_source_contribution(source="hal")
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"source_contribution_id": sa, "person_id": pid},
        )
        assert r.status_code == 200
        with owner_pool() as cur:
            cur.execute("SELECT person_id FROM source_contributions WHERE id = %s", (sa,))
            assert cur.fetchone()["person_id"] == pid

    def test_ok_with_create_person(self, auth_client):
        sa = seed_source_contribution(source="hal")
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={
                "source_contribution_id": sa,
                "create_person": {"last_name": "Créée", "first_name": "Ici"},
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_blocked_when_pair_rejected(self, auth_client):
        pid = seed_person()
        sa, publication = _seed_orphan_with_publication()
        seed_rejected_contribution(publication, person_id=pid)
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"source_contribution_id": sa, "person_id": pid},
        )
        assert r.status_code == 409
        pair = r.json()["rejected_pairs"][0]
        assert pair["publication_id"] == publication
        assert pair["person_id"] == pid
        assert pair["rejected_at"]

    def test_forced_unrejects_and_assigns(self, auth_client):
        pid = seed_person()
        sa, publication = _seed_orphan_with_publication()
        seed_rejected_contribution(publication, person_id=pid)
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"source_contribution_id": sa, "person_id": pid, "force": True},
        )
        assert r.status_code == 200
        assert r.json()["person_id"] == pid


class TestBatchAssignOrphanContributions:
    def test_empty_contributions_ok_zero(self, auth_client):
        pid = seed_person()
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"source_contribution_ids": [], "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 0

    def test_person_not_found(self, auth_client):
        sa = seed_source_contribution(source="hal")
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"source_contribution_ids": [sa], "person_id": 999999999},
        )
        assert r.status_code == 404

    def test_ok(self, auth_client):
        pid = seed_person()
        sa1 = seed_source_contribution(source="hal")
        sa2 = seed_source_contribution(source="openalex")
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"source_contribution_ids": [sa1, sa2], "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] >= 0

    def test_blocked_when_pair_rejected(self, auth_client):
        pid = seed_person()
        sa, publication = _seed_orphan_with_publication()
        seed_rejected_contribution(publication, person_id=pid)
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"source_contribution_ids": [sa], "person_id": pid},
        )
        assert r.status_code == 409
        assert r.json()["rejected_pairs"][0]["publication_id"] == publication

    def test_forced_unrejects_and_assigns(self, auth_client):
        pid = seed_person()
        sa, publication = _seed_orphan_with_publication()
        seed_rejected_contribution(publication, person_id=pid)
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"source_contribution_ids": [sa], "person_id": pid, "force": True},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 1
