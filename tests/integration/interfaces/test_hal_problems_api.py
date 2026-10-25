"""Tests d'intégration pour `interfaces.api.routers.hal_problems`.

Couvre :
- GET /api/hal-problems/duplicate-accounts
- GET /api/hal-problems/duplicate-publications-doi
- GET /api/hal-problems/duplicate-publications-meta
- GET /api/hal-problems/missing-collections (lab_id requis, 422 sans collection)
- GET /api/hal-problems/missing-collections/labs
- GET /api/hal-problems/affiliation-conflicts
"""

from __future__ import annotations

from tests.integration.helpers.seeds import (
    seed_add_to_perimeter,
    seed_config,
    seed_structure,
    uniq,
)


def _seed_lab(code: str | None = None, hal_collection: str | None = None) -> int:
    lab_id = seed_structure(code or uniq("LAB"), hal_collection=hal_collection)
    # Rattache au périmètre persons, désigné en configuration : les lectures HAL
    # scopent au périmètre, pas au type de structure.
    seed_config("perimeter_persons", "uca")
    seed_add_to_perimeter(lab_id, code="uca", name="test persons perimeter")
    return lab_id


class TestDuplicateAccounts:
    def test_returns_paginated_shape(self, client):
        r = client.get("/api/hal-problems/duplicate-accounts")
        assert r.status_code == 200
        body = r.json()
        # Forme commune : total + page + per_page + items.
        assert "total" in body

    def test_per_page_above_limit_rejected(self, client):
        r = client.get("/api/hal-problems/duplicate-accounts", params={"per_page": 500})
        assert r.status_code == 422

    def test_accepts_a_single_result_per_page(self, client):
        """Aucun plancher au-delà de la page non vide : demander une ligne est une demande légitime."""
        r = client.get("/api/hal-problems/duplicate-accounts", params={"per_page": 1})
        assert r.status_code == 200

    def test_empty_page_rejected(self, client):
        r = client.get("/api/hal-problems/duplicate-accounts", params={"per_page": 0})
        assert r.status_code == 422


class TestDuplicatePublicationsDoi:
    def test_returns_200(self, client):
        r = client.get("/api/hal-problems/duplicate-publications-doi")
        assert r.status_code == 200

    def test_pagination_params(self, client):
        r = client.get(
            "/api/hal-problems/duplicate-publications-doi", params={"page": 2, "per_page": 20}
        )
        assert r.status_code == 200


class TestDuplicatePublicationsMeta:
    def test_returns_200(self, client):
        r = client.get("/api/hal-problems/duplicate-publications-meta")
        assert r.status_code == 200


class TestMissingCollections:
    def test_requires_lab_id(self, client):
        # `lab_id` est Query(...) — obligatoire, 422 si absent.
        r = client.get("/api/hal-problems/missing-collections")
        assert r.status_code == 422

    def test_422_when_lab_has_no_hal_collection(self, client):
        """Le laboratoire existe, mais sans collection il n'y a rien à quoi comparer."""
        lab = _seed_lab(hal_collection=None)
        r = client.get("/api/hal-problems/missing-collections", params={"lab_id": lab})
        assert r.status_code == 422
        assert "collection" in r.json()["detail"]

    def test_404_when_lab_is_unknown(self, client):
        """L'absence de laboratoire et l'absence de collection ne se disent pas du même statut."""
        r = client.get("/api/hal-problems/missing-collections", params={"lab_id": 999999})
        assert r.status_code == 404

    def test_returns_results_when_lab_has_collection(self, client):
        lab = _seed_lab(hal_collection="MY-LAB-COLL")
        r = client.get("/api/hal-problems/missing-collections", params={"lab_id": lab})
        assert r.status_code == 200
        body = r.json()
        # Forme : `{total, page, per_page, items}` (sans `error`).
        assert "total" in body


class TestMissingCollectionsLabs:
    def test_returns_list(self, client):
        r = client.get("/api/hal-problems/missing-collections/labs")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_includes_labs_with_collection(self, client):
        lab = _seed_lab(hal_collection="LISTED-COLL")
        r = client.get("/api/hal-problems/missing-collections/labs")
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()]
        assert lab in ids


class TestAffiliationConflicts:
    def test_returns_paginated_shape(self, client):
        r = client.get("/api/hal-problems/affiliation-conflicts")
        assert r.status_code == 200
        assert "total" in r.json()

    def test_pagination_params(self, client):
        r = client.get(
            "/api/hal-problems/affiliation-conflicts",
            params={"page": 1, "per_page": 50},
        )
        assert r.status_code == 200
