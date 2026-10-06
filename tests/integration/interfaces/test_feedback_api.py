"""Tests de caractérisation pour le router feedback.

Couvre :
- /api/feedback/stats : cas vide + cas avec données (branches des COUNT FILTER)
- /api/feedback/false-negatives : cas vide + cas avec données + filtre search
- /api/feedback/false-positives : idem
"""

import pytest

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import (
    seed_address,
    seed_structure,
    seed_structure_name_form,
    uniq,
)


def _seed_ast(
    address_id: int,
    structure_id: int,
    matched_form_id: int | None = None,
    is_confirmed: bool | None = None,
) -> int:
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO address_structures (address_id, structure_id, matched_form_id, is_confirmed) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (address_id, structure_id, matched_form_id, is_confirmed),
        )
        return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with owner_pool() as cur:
        cur.execute(
            "TRUNCATE TABLE address_structures, addresses, structure_name_forms, "
            "structures, audit_log RESTART IDENTITY CASCADE"
        )


# ── /api/feedback/stats ───────────────────────────────────


class TestFeedbackStats:
    def test_empty_structure(self, client):
        sid = seed_structure()
        r = client.get("/api/feedback/stats", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total_reviewed"] == 0
        assert body["detection_rate"] is None
        assert body["false_negatives"] == 0
        assert body["false_positives"] == 0
        assert body["concordant_valid"] == 0
        assert body["pending"] == 0

    def test_with_all_categories(self, client):
        sid = seed_structure()
        fid = seed_structure_name_form(sid)

        # concordant_valid : confirmed + detected
        a1 = seed_address(uniq("a1"))
        _seed_ast(a1, sid, matched_form_id=fid, is_confirmed=True)

        # concordant_rejected : rejected + not detected
        a2 = seed_address(uniq("a2"))
        _seed_ast(a2, sid, matched_form_id=None, is_confirmed=False)

        # false_negative : confirmed mais non détectée
        a3 = seed_address(uniq("a3"))
        _seed_ast(a3, sid, matched_form_id=None, is_confirmed=True)

        # false_positive : détectée mais rejetée
        a4 = seed_address(uniq("a4"))
        _seed_ast(a4, sid, matched_form_id=fid, is_confirmed=False)

        # pending : détectée mais pas encore review
        a5 = seed_address(uniq("a5"))
        _seed_ast(a5, sid, matched_form_id=fid, is_confirmed=None)

        r = client.get("/api/feedback/stats", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total_reviewed"] == 4
        # 2 concordants sur 4 reviewed = 50%
        assert body["detection_rate"] == 50.0
        assert body["false_negatives"] == 1
        assert body["false_positives"] == 1
        assert body["concordant_valid"] == 1
        assert body["pending"] == 1

    def test_missing_structure_id(self, client):
        r = client.get("/api/feedback/stats")
        assert r.status_code == 422


# ── /api/feedback/false-negatives ─────────────────────────


class TestFeedbackFalseNegatives:
    def test_empty(self, client):
        sid = seed_structure()
        r = client.get("/api/feedback/false-negatives", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["addresses"] == []

    def test_with_results(self, client):
        sid = seed_structure()
        a = seed_address("Université de Clermont-Ferrand FN")
        _seed_ast(a, sid, matched_form_id=None, is_confirmed=True)

        r = client.get("/api/feedback/false-negatives", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_search_filter(self, client):
        sid = seed_structure()
        target = seed_address("Marqueur Unique Search Target")
        _seed_ast(target, sid, matched_form_id=None, is_confirmed=True)
        # Bruit non matché
        other = seed_address("Paris")
        _seed_ast(other, sid, matched_form_id=None, is_confirmed=True)

        r = client.get(
            "/api/feedback/false-negatives",
            params={"structure_id": sid, "search": "Marqueur"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_pagination(self, client):
        sid = seed_structure()
        r = client.get(
            "/api/feedback/false-negatives",
            params={"structure_id": sid, "page": 2, "per_page": 10},
        )
        assert r.status_code == 200


# ── /api/feedback/false-positives ─────────────────────────


class TestFeedbackFalsePositives:
    def test_empty(self, client):
        sid = seed_structure()
        r = client.get("/api/feedback/false-positives", params={"structure_id": sid})
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_with_results(self, client):
        sid = seed_structure()
        fid = seed_structure_name_form(sid)
        a = seed_address("Adresse FP détectée mais rejetée")
        _seed_ast(a, sid, matched_form_id=fid, is_confirmed=False)

        r = client.get("/api/feedback/false-positives", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_search_filter(self, client):
        sid = seed_structure()
        fid = seed_structure_name_form(sid)
        target = seed_address("FPUnique Target Address")
        _seed_ast(target, sid, matched_form_id=fid, is_confirmed=False)
        other = seed_address("Lyon")
        _seed_ast(other, sid, matched_form_id=fid, is_confirmed=False)

        r = client.get(
            "/api/feedback/false-positives",
            params={"structure_id": sid, "search": "FPUnique"},
        )
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_pagination(self, client):
        sid = seed_structure()
        r = client.get(
            "/api/feedback/false-positives",
            params={"structure_id": sid, "page": 2, "per_page": 10},
        )
        assert r.status_code == 200
