"""Tests de caractérisation pour le router admin_feedback.

Couvre :
- /api/admin/feedback/stats : cas vide + cas avec données (branches des COUNT FILTER)
- /api/admin/feedback/false-negatives : cas vide + cas avec données + filtre search
- /api/admin/feedback/false-positives : idem
- /api/admin/feedback/rerun : script introuvable (branche 500)

Le /rerun happy-path n'est pas testé car il lance un subprocess réel
(resolve_addresses.py) ; de toute façon le chemin compilé dans le router
pointe sur `interfaces/api/processing/` qui n'existe plus (script déplacé
en `interfaces/cli/pipeline/`) — la branche 500 est donc la seule
actuellement fonctionnelle.
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


def _seed_structure(type_: str = "labo") -> int:
    code = _uniq("FBK")
    with _pool() as cur:
        cur.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (%s, %s, %s::structure_type) RETURNING id",
            (code, code, type_),
        )
        return cur.fetchone()["id"]


def _seed_name_form(structure_id: int) -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO structure_name_forms (structure_id, form_text) "
            "VALUES (%s, %s) RETURNING id",
            (structure_id, _uniq("form")),
        )
        return cur.fetchone()["id"]


def _seed_address(raw_text: str, pub_count: int = 1) -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO addresses (raw_text, normalized_text, pub_count) "
            "VALUES (%s, lower(%s), %s) RETURNING id",
            (raw_text, raw_text, pub_count),
        )
        return cur.fetchone()["id"]


def _seed_ast(
    address_id: int,
    structure_id: int,
    matched_form_id: int | None = None,
    is_confirmed: bool | None = None,
) -> int:
    with _pool() as cur:
        cur.execute(
            "INSERT INTO address_structures (address_id, structure_id, matched_form_id, is_confirmed) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (address_id, structure_id, matched_form_id, is_confirmed),
        )
        return cur.fetchone()["id"]


@pytest.fixture(scope="module", autouse=True)
def _cleanup_after_module():
    yield
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE address_structures, addresses, structure_name_forms, "
            "structures, audit_log RESTART IDENTITY CASCADE"
        )


# ── /api/admin/feedback/structures ──────────────────────────────


class TestFeedbackStructures:
    def test_groups_by_type_and_returns_uca_as_default(self, client):
        """UCA (code = 'uca') est renvoyée comme default_structure_id."""
        with _pool() as cur:
            cur.execute(
                "INSERT INTO structures (code, name, structure_type) "
                "VALUES (%s, %s, 'universite'::structure_type) RETURNING id",
                ("uca", "Université Clermont Auvergne"),
            )
            uca_id = cur.fetchone()["id"]

        labo_id = _seed_structure(type_="labo")

        r = client.get("/api/admin/feedback/structures")
        assert r.status_code == 200
        body = r.json()
        assert body["default_structure_id"] == uca_id
        # Les deux structures sont groupées par type
        assert uca_id in [s["id"] for s in body["by_type"]["universite"]]
        assert labo_id in [s["id"] for s in body["by_type"]["labo"]]

    def test_fallback_default_respects_type_order(self, client):
        """Sans UCA, le default est une structure du type le plus haut dans
        l'ordre universite > onr > chu > ecole > labo parmi les types
        présents en base. On vérifie l'ordre, pas un id précis, parce que
        la base peut déjà contenir d'autres structures d'autres suites."""
        with _pool() as cur:
            cur.execute("DELETE FROM structures WHERE code = 'uca'")

        _seed_structure(type_="labo")
        _seed_structure(type_="chu")

        r = client.get("/api/admin/feedback/structures")
        assert r.status_code == 200
        body = r.json()
        default_id = body["default_structure_id"]
        assert default_id is not None

        # Retrouver le type du default dans by_type
        default_type = next(
            t for t, items in body["by_type"].items() if any(s["id"] == default_id for s in items)
        )
        order = ("universite", "onr", "chu", "ecole", "labo")
        # Le type du default doit être le premier type présent dans `order`
        first_present = next(t for t in order if body["by_type"].get(t))
        assert default_type == first_present

    def test_excludes_non_eligible_types(self, client):
        """Les types hors (universite/onr/chu/ecole/labo) sont ignorés :
        site, equipe, autre ne doivent pas apparaître."""
        _seed_structure(type_="site")
        _seed_structure(type_="autre")

        r = client.get("/api/admin/feedback/structures")
        assert r.status_code == 200
        body = r.json()
        assert "site" not in body["by_type"]
        assert "autre" not in body["by_type"]


# ── /api/admin/feedback/stats ───────────────────────────────────


class TestFeedbackStats:
    def test_empty_structure(self, client):
        sid = _seed_structure()
        r = client.get("/api/admin/feedback/stats", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total_reviewed"] == 0
        assert body["detection_rate"] is None
        assert body["false_negatives"] == 0
        assert body["false_positives"] == 0
        assert body["concordant_valid"] == 0
        assert body["pending"] == 0

    def test_with_all_categories(self, client):
        sid = _seed_structure()
        fid = _seed_name_form(sid)

        # concordant_valid : confirmed + detected
        a1 = _seed_address(_uniq("a1"))
        _seed_ast(a1, sid, matched_form_id=fid, is_confirmed=True)

        # concordant_rejected : rejected + not detected
        a2 = _seed_address(_uniq("a2"))
        _seed_ast(a2, sid, matched_form_id=None, is_confirmed=False)

        # false_negative : confirmed mais non détectée
        a3 = _seed_address(_uniq("a3"))
        _seed_ast(a3, sid, matched_form_id=None, is_confirmed=True)

        # false_positive : détectée mais rejetée
        a4 = _seed_address(_uniq("a4"))
        _seed_ast(a4, sid, matched_form_id=fid, is_confirmed=False)

        # pending : détectée mais pas encore review
        a5 = _seed_address(_uniq("a5"))
        _seed_ast(a5, sid, matched_form_id=fid, is_confirmed=None)

        r = client.get("/api/admin/feedback/stats", params={"structure_id": sid})
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
        r = client.get("/api/admin/feedback/stats")
        assert r.status_code == 422


# ── /api/admin/feedback/false-negatives ─────────────────────────


class TestFeedbackFalseNegatives:
    def test_empty(self, client):
        sid = _seed_structure()
        r = client.get("/api/admin/feedback/false-negatives", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["addresses"] == []

    def test_with_results(self, client):
        sid = _seed_structure()
        a = _seed_address("Université de Clermont-Ferrand FN")
        _seed_ast(a, sid, matched_form_id=None, is_confirmed=True)

        r = client.get("/api/admin/feedback/false-negatives", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_search_filter(self, client):
        sid = _seed_structure()
        target = _seed_address("Marqueur Unique Search Target")
        _seed_ast(target, sid, matched_form_id=None, is_confirmed=True)
        # Bruit non matché
        other = _seed_address("Paris")
        _seed_ast(other, sid, matched_form_id=None, is_confirmed=True)

        r = client.get(
            "/api/admin/feedback/false-negatives",
            params={"structure_id": sid, "search": "Marqueur"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_pagination(self, client):
        sid = _seed_structure()
        r = client.get(
            "/api/admin/feedback/false-negatives",
            params={"structure_id": sid, "page": 2, "per_page": 10},
        )
        assert r.status_code == 200


# ── /api/admin/feedback/false-positives ─────────────────────────


class TestFeedbackFalsePositives:
    def test_empty(self, client):
        sid = _seed_structure()
        r = client.get("/api/admin/feedback/false-positives", params={"structure_id": sid})
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_with_results(self, client):
        sid = _seed_structure()
        fid = _seed_name_form(sid)
        a = _seed_address("Adresse FP détectée mais rejetée")
        _seed_ast(a, sid, matched_form_id=fid, is_confirmed=False)

        r = client.get("/api/admin/feedback/false-positives", params={"structure_id": sid})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1

    def test_search_filter(self, client):
        sid = _seed_structure()
        fid = _seed_name_form(sid)
        target = _seed_address("FPUnique Target Address")
        _seed_ast(target, sid, matched_form_id=fid, is_confirmed=False)
        other = _seed_address("Lyon")
        _seed_ast(other, sid, matched_form_id=fid, is_confirmed=False)

        r = client.get(
            "/api/admin/feedback/false-positives",
            params={"structure_id": sid, "search": "FPUnique"},
        )
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_pagination(self, client):
        sid = _seed_structure()
        r = client.get(
            "/api/admin/feedback/false-positives",
            params={"structure_id": sid, "page": 2, "per_page": 10},
        )
        assert r.status_code == 200


# ── /api/admin/feedback/rerun ───────────────────────────────────


class TestFeedbackRerun:
    def test_script_missing_returns_500(self, client):
        """Le chemin compilé pointe sur interfaces/api/processing/resolve_addresses.py
        qui n'existe plus (script déplacé vers interfaces/cli/pipeline/).
        C'est un bug latent — en attendant, le router renvoie 500."""
        r = client.get("/api/admin/feedback/rerun")
        assert r.status_code == 500
