"""Tests de caractérisation pour le router `admin/contributions`.

Couvre :
- PATCH /api/contributions/{id}/exclude
- GET / POST /api/contributions/orphans/*

Stratégie : seed minimal via un pool dédié (hors pool API), ids uniques par
test pour éviter les collisions.
"""

import uuid

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    publication_perimeter_evidence,
    seed_alignment,
    seed_contribution,
    seed_perimeter_author_contribution,
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


def _seed_orphan_with_publication(raw_author_name: str = "Reject Me") -> tuple[int, int]:
    """Contribution orpheline : contribution d'auteur du périmètre sans personne, d'une contribution source de nom brut `raw_author_name`, dans une publication.

    Renvoie (contribution, publication) pour pouvoir rejeter la paire."""
    publication_id = seed_publication(title=uniq("Pub"))
    source_record_id = seed_source_record(publication_id=publication_id)
    source_contribution_id = seed_source_contribution(
        source="hal", source_record_id=source_record_id, raw_author_name=raw_author_name
    )
    contribution_id = seed_alignment(publication_id, [(source_contribution_id, source_record_id)])
    seed_perimeter_author_contribution(contribution_id)
    return contribution_id, publication_id


def _seed_orphan() -> int:
    """Contribution d'une contribution orpheline, dans sa publication."""
    return _seed_orphan_with_publication()[0]


# ── PATCH /api/contributions/{id}/exclude ─────────────────────────


def _contribution_id(publication_id: int, person_id: int | None) -> int:
    """L'`id` de la contribution de la personne `person_id` dans la publication, ou de la contribution sans personne si `person_id` vaut `None`."""
    with owner_pool() as cur:
        cur.execute(
            "SELECT id FROM contributions"
            " WHERE publication_id = %s AND person_id IS NOT DISTINCT FROM %s",
            (publication_id, person_id),
        )
        return cur.fetchone()["id"]


class TestExcludeContribution:
    def test_ok(self, auth_client):
        pid = seed_person()
        publication = seed_publication("Exclude test")
        seed_contribution(publication, person_id=pid, in_perimeter=True)
        r = auth_client.patch(f"/api/contributions/{_contribution_id(publication, pid)}/exclude")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_exclusion_takes_the_publication_out_of_the_perimeter(self, auth_client):
        pid = seed_person()
        publication = seed_publication(uniq("Pub"), in_perimeter=True)
        seed_source_record(publication_id=publication)
        seed_contribution(publication, person_id=pid, in_perimeter=True, roles=["author"])

        r = auth_client.patch(f"/api/contributions/{_contribution_id(publication, pid)}/exclude")

        assert r.status_code == 200
        assert publication_perimeter_evidence(publication) == []

    def test_contribution_without_person_is_not_found(self, auth_client):
        """L'id d'une contribution sans personne ne désigne pas une contribution."""
        contribution, _ = _seed_orphan_with_publication()
        r = auth_client.patch(f"/api/contributions/{contribution}/exclude")
        assert r.status_code == 404


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
        assert item["sources"] == ["hal"]

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
        contribution = _seed_orphan()
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"contribution_id": contribution},
        )
        assert r.status_code == 422

    def test_create_person_empty_name(self, auth_client):
        contribution = _seed_orphan()
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={
                "contribution_id": contribution,
                "create_person": {"last_name": "   ", "first_name": "X"},
            },
        )
        assert r.status_code == 422

    def test_person_not_found(self, auth_client):
        contribution = _seed_orphan()
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"contribution_id": contribution, "person_id": 999999999},
        )
        assert r.status_code == 404

    def test_ok_with_person_id(self, auth_client):
        pid = seed_person()
        contribution = _seed_orphan()
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"contribution_id": contribution, "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["person_id"] == pid

    def test_assign_visible_immediately(self, auth_client):
        # La requête est committée avant l'envoi de la réponse : le rattachement est lisible
        # depuis une connexion indépendante.
        pid = seed_person()
        contribution = _seed_orphan()
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"contribution_id": contribution, "person_id": pid},
        )
        assert r.status_code == 200
        with owner_pool() as cur:
            cur.execute("SELECT person_id FROM contributions WHERE id = %s", (contribution,))
            assert cur.fetchone()["person_id"] == pid

    def test_assignment_brings_the_publication_into_the_perimeter(self, auth_client):
        pid = seed_person()
        contribution, publication = _seed_orphan_with_publication()

        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"contribution_id": contribution, "person_id": pid},
        )

        assert r.status_code == 200
        assert publication_perimeter_evidence(publication) == ["address"]

    def test_ok_with_create_person(self, auth_client):
        contribution = _seed_orphan()
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={
                "contribution_id": contribution,
                "create_person": {"last_name": "Créée", "first_name": "Ici"},
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_blocked_when_pair_rejected(self, auth_client):
        pid = seed_person()
        contribution, publication = _seed_orphan_with_publication()
        seed_rejected_contribution(publication, person_id=pid)
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"contribution_id": contribution, "person_id": pid},
        )
        assert r.status_code == 409
        pair = r.json()["rejected_pairs"][0]
        assert pair["publication_id"] == publication
        assert pair["person_id"] == pid
        assert pair["rejected_at"]

    def test_forced_unrejects_and_assigns(self, auth_client):
        pid = seed_person()
        contribution, publication = _seed_orphan_with_publication()
        seed_rejected_contribution(publication, person_id=pid)
        r = auth_client.post(
            "/api/contributions/orphans/assign",
            json={"contribution_id": contribution, "person_id": pid, "force": True},
        )
        assert r.status_code == 200
        assert r.json()["person_id"] == pid


class TestBatchAssignOrphanContributions:
    def test_empty_contributions_ok_zero(self, auth_client):
        pid = seed_person()
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"contribution_ids": [], "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 0

    def test_person_not_found(self, auth_client):
        contribution = _seed_orphan()
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"contribution_ids": [contribution], "person_id": 999999999},
        )
        assert r.status_code == 404

    def test_ok(self, auth_client):
        pid = seed_person()
        contributions = [_seed_orphan(), _seed_orphan()]
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"contribution_ids": contributions, "person_id": pid},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 2

    def test_blocked_when_pair_rejected(self, auth_client):
        pid = seed_person()
        contribution, publication = _seed_orphan_with_publication()
        seed_rejected_contribution(publication, person_id=pid)
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"contribution_ids": [contribution], "person_id": pid},
        )
        assert r.status_code == 409
        assert r.json()["rejected_pairs"][0]["publication_id"] == publication

    def test_forced_unrejects_and_assigns(self, auth_client):
        pid = seed_person()
        contribution, publication = _seed_orphan_with_publication()
        seed_rejected_contribution(publication, person_id=pid)
        r = auth_client.post(
            "/api/contributions/orphans/batch-assign",
            json={"contribution_ids": [contribution], "person_id": pid, "force": True},
        )
        assert r.status_code == 200
        assert r.json()["assigned"] == 1
