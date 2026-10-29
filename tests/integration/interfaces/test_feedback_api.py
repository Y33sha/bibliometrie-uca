"""Tests de caractérisation du router de retour sur la détection des adresses.

Couvre :
- /api/feedback/stats : structure vide, et une adresse par catégorie ;
- /api/feedback/false-negatives et /api/feedback/false-positives : liste vide, résultats, recherche, pagination.
"""

from tests.integration.helpers.seeds import (
    seed_address,
    seed_address_structure,
    seed_structure,
    seed_structure_name_form,
    uniq,
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

        # Concordance positive : détectée et confirmée.
        a1 = seed_address(uniq("a1"))
        seed_address_structure(a1, structure_id=sid, matched_form_id=fid, is_confirmed=True)

        # Concordance négative : non détectée et rejetée.
        a2 = seed_address(uniq("a2"))
        seed_address_structure(a2, structure_id=sid, is_confirmed=False)

        # Faux négatif : confirmée sans être détectée.
        a3 = seed_address(uniq("a3"))
        seed_address_structure(a3, structure_id=sid, is_confirmed=True)

        # Faux positif : détectée et rejetée.
        a4 = seed_address(uniq("a4"))
        seed_address_structure(a4, structure_id=sid, matched_form_id=fid, is_confirmed=False)

        # En attente : détectée, sans décision.
        a5 = seed_address(uniq("a5"))
        seed_address_structure(a5, structure_id=sid, matched_form_id=fid)

        r = client.get("/api/feedback/stats", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total_reviewed"] == 4
        # Deux concordances sur quatre décisions : 50 %.
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
        seed_address_structure(a, structure_id=sid, is_confirmed=True)

        r = client.get("/api/feedback/false-negatives", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_search_filter(self, client):
        sid = seed_structure()
        target = seed_address("Marqueur Unique Search Target")
        seed_address_structure(target, structure_id=sid, is_confirmed=True)
        # Adresse hors de la recherche.
        other = seed_address("Paris")
        seed_address_structure(other, structure_id=sid, is_confirmed=True)

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
        seed_address_structure(a, structure_id=sid, matched_form_id=fid, is_confirmed=False)

        r = client.get("/api/feedback/false-positives", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_search_filter(self, client):
        sid = seed_structure()
        fid = seed_structure_name_form(sid)
        target = seed_address("FPUnique Target Address")
        seed_address_structure(target, structure_id=sid, matched_form_id=fid, is_confirmed=False)
        other = seed_address("Lyon")
        seed_address_structure(other, structure_id=sid, matched_form_id=fid, is_confirmed=False)

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
