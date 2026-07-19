"""Tests de caractérisation pour le router addresses.

Stratégie : exercer toutes les branches des endpoints pour verrouiller
le comportement. Même approche que test_persons_api.py : tester le
status code sur une base non-contrôlée, ajouter un seed minimal
(module-scope) pour les endpoints qui exigent un pays ou un périmètre.
"""

import os
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
    """Connexion directe (hors pool) pour le seed. Évite les interactions
    subtiles avec le pool partagé par l'API (qui peut fermer ses curseurs
    à des moments inattendus)."""
    conn = psycopg.connect(**_DB_ARGS, row_factory=dict_row)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


@pytest.fixture(scope="module", autouse=True)
def _seed_addresses_api(client):
    """Seed minimal pour les tests addresses : pays FR + périmètre uca.

    Effectue aussi un `warmup` via client : le conftest racine recrée la
    base via `pg_terminate_backend` au démarrage, ce qui tue les
    connexions déjà ouvertes par la pool de `conftest.py`. Un premier
    appel à l'API purge ces connexions mortes (la pool les discard au
    retour). `client` dépendance → fixture lancée après la création du
    TestClient.

    Teardown : TRUNCATE des tables touchées + suppression du périmètre
    'uca' et de la config `perimeter_persons` pour ne pas polluer les
    suites application qui réinsèrent ces mêmes clés via leurs propres
    fixtures (test_addresses_service, test_authorships_service,
    test_persons_service).
    """
    with _pool() as cur:
        cur.execute(
            "INSERT INTO countries (code, name) VALUES ('FR', 'France') ON CONFLICT DO NOTHING"
        )
        # Code unique pour éviter les collisions avec d'autres tests d'intégration
        # qui insèrent aussi une structure 'UCA' en dur.
        cur.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES ('UCA-ADDR-API-SEED', 'UCA seed', 'universite') "
            "ON CONFLICT (code) DO NOTHING RETURNING id"
        )
        row = cur.fetchone()
        if row:
            uca_id = row["id"]
        else:
            cur.execute("SELECT id FROM structures WHERE code = 'UCA-ADDR-API-SEED'")
            uca_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO perimeters (code, name, structure_ids) VALUES ('uca', 'UCA', %s) "
            "ON CONFLICT (code) DO UPDATE SET structure_ids = EXCLUDED.structure_ids",
            ([uca_id],),
        )
        cur.execute(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', to_jsonb('uca'::text)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )

    # Warmup : ping l'API jusqu'à ce qu'une connexion vive soit obtenue
    # (purge les connexions mortes de la pool).
    for _ in range(5):
        r = client.get("/api/countries")
        if r.status_code == 200:
            break

    yield

    # Teardown : nettoyer ce que ce module a committé (seed + état modifié
    # par les routes API mutantes). RESTART IDENTITY évite que les ids
    # autoincrémentés ne soient consultés par des tests ultérieurs.
    with _pool() as cur:
        cur.execute(
            "TRUNCATE TABLE address_structures, source_authorship_addresses, addresses, "
            "structure_name_forms, structure_relations, structures, perimeters, "
            "audit_log RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM config WHERE key = 'perimeter_persons'")


def _seed_address(raw_text, countries=None):
    with _pool() as cur:
        cur.execute(
            "INSERT INTO addresses (raw_text, normalized_text, countries) "
            "VALUES (%s, lower(%s), %s) RETURNING id",
            (raw_text, raw_text, countries),
        )
        return cur.fetchone()["id"]


def _seed_structure(code):
    with _pool() as cur:
        cur.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (%s, %s, 'labo') RETURNING id",
            (code, code),
        )
        return cur.fetchone()["id"]


# ── GET /api/addresses ───────────────────────────────────────────


class TestListAddresses:
    def test_no_structure_and_no_search_triggers_guard(self, client):
        # Garde-fou : detected=no sans search → requires_search (pas d'accès DB)
        r = client.get("/api/addresses", params={"detected": "no"})
        assert r.status_code == 200
        assert r.json().get("requires_search") is True

    def test_with_structure_id(self, client):
        r = client.get("/api/addresses", params={"structure_id": 1})
        assert r.status_code == 200

    def test_validation_confirmed(self, client):
        r = client.get("/api/addresses", params={"validation": "confirmed"})
        assert r.status_code == 200

    def test_validation_rejected(self, client):
        r = client.get("/api/addresses", params={"validation": "rejected"})
        assert r.status_code == 200

    def test_text_predicates_repeated(self, client):
        r = client.get(
            "/api/addresses",
            params={"text": ["contains:Clermont", "not_contains:Toulouse"]},
        )
        assert r.status_code == 200

    def test_struct_predicate(self, client):
        r = client.get("/api/addresses", params={"struct": "recognized:1,2"})
        assert r.status_code == 200

    def test_struct_predicate_lifts_guard(self, client):
        # detected=no SANS texte mais AVEC un prédicat structure → pas de garde-fou,
        # la requête accède à la DB et renvoie une liste normale.
        r = client.get("/api/addresses", params={"detected": "no", "struct": "recognized:1"})
        assert r.status_code == 200
        assert r.json().get("requires_search") is not True


class TestMalformedPredicates:
    """Un prédicat qui ne se conforme pas à sa forme est refusé, non abandonné.

    Abandonné, il rendait la liste non filtrée sous un code 200 : le résultat n'était pas
    celui qu'on croyait, et rien ne le signalait.
    """

    @pytest.mark.parametrize(
        "text",
        ["bogus:Clermont", "contains:", "nocolon", ":Clermont"],
    )
    def test_refuses_malformed_text_predicate(self, client, text):
        r = client.get("/api/addresses", params={"text": text})
        assert r.status_code == 422

    @pytest.mark.parametrize(
        "struct",
        ["bogus:1", "recognized:abc", "recognized:", "recognized:1,", "recognized"],
    )
    def test_refuses_malformed_structure_predicate(self, client, struct):
        r = client.get("/api/addresses", params={"struct": struct})
        assert r.status_code == 422

    def test_refuses_a_lot_where_one_occurrence_is_malformed(self, client):
        r = client.get("/api/addresses", params={"text": ["contains:Clermont", "bogus:Toulouse"]})
        assert r.status_code == 422


# ── GET /api/addresses/{addr_id}/publications ────────────────────


class TestGetAddressPublications:
    def test_404_missing(self, client):
        r = client.get("/api/addresses/999999999/publications")
        assert r.status_code == 404

    def test_200_when_address_exists(self, client):
        addr = _seed_address("Addr pubs test")
        r = client.get(f"/api/addresses/{addr}/publications")
        assert r.status_code == 200
        assert r.json()["address_id"] == addr


# ── POST /api/addresses/{addr_id}/review ─────────────────────────


class TestReviewAddress:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/addresses/1/review",
            json={"structure_id": 1, "is_confirmed": True},
        )
        assert r.status_code == 401

    def test_confirm(self, auth_client):
        addr = _seed_address("Review confirm")
        struct = _seed_structure("LAB-REV-CONF")
        r = auth_client.post(
            f"/api/addresses/{addr}/review",
            json={"structure_id": struct, "is_confirmed": True},
        )
        assert r.status_code == 200
        assert r.json()["is_confirmed"] is True

    def test_reject(self, auth_client):
        addr = _seed_address("Review reject")
        struct = _seed_structure("LAB-REV-REJ")
        r = auth_client.post(
            f"/api/addresses/{addr}/review",
            json={"structure_id": struct, "is_confirmed": False},
        )
        assert r.status_code == 200

    def test_reset(self, auth_client):
        addr = _seed_address("Review reset")
        struct = _seed_structure("LAB-REV-RES")
        r = auth_client.post(
            f"/api/addresses/{addr}/review",
            json={"structure_id": struct, "is_confirmed": None},
        )
        assert r.status_code == 200


# ── POST /api/addresses/batch-review ─────────────────────────────


class TestBatchReview:
    def test_requires_admin(self, client):
        r = client.post(
            "/api/addresses/batch-review",
            json={"address_ids": [], "structure_id": 1, "is_confirmed": True},
        )
        assert r.status_code == 401

    def test_empty_batch(self, auth_client):
        struct = _seed_structure("LAB-BATCH-EMPTY")
        r = auth_client.post(
            "/api/addresses/batch-review",
            json={"address_ids": [], "structure_id": struct, "is_confirmed": True},
        )
        assert r.status_code == 200
        assert r.json()["updated"] == 0

    def test_non_empty_batch(self, auth_client):
        a1 = _seed_address("Batch a1")
        a2 = _seed_address("Batch a2")
        struct = _seed_structure("LAB-BATCH-NE")
        r = auth_client.post(
            "/api/addresses/batch-review",
            json={"address_ids": [a1, a2], "structure_id": struct, "is_confirmed": True},
        )
        assert r.status_code == 200
        assert r.json()["updated"] == 2


# ── GET /api/countries + /api/addresses/countries ────────────────


class TestCountries:
    def test_list_countries(self, client):
        r = client.get("/api/countries")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_addresses_countries_default(self, client):
        r = client.get("/api/addresses/countries")
        assert r.status_code == 200
        data = r.json()
        assert "addresses" in data and "country_facets" in data

    def test_addresses_countries_has_country_yes(self, client):
        r = client.get("/api/addresses/countries", params={"has_country": "yes"})
        assert r.status_code == 200

    def test_addresses_countries_has_country_no(self, client):
        r = client.get("/api/addresses/countries", params={"has_country": "no"})
        assert r.status_code == 200

    def test_addresses_countries_suggest_mode(self, client):
        r = client.get("/api/addresses/countries", params={"suggest": True})
        assert r.status_code == 200
        assert "suggestion_facets" in r.json()

    def test_addresses_countries_filter_by_country(self, client):
        r = client.get("/api/addresses/countries", params={"country_code": "FR"})
        assert r.status_code == 200

    def test_addresses_countries_filter_by_suggested(self, client):
        r = client.get("/api/addresses/countries", params={"suggested_country": "FR"})
        assert r.status_code == 200


# ── GET /api/addresses/suggest-countries ─────────────────────────


# ── POST /api/addresses/{addr_id}/country ────────────────────────


class TestSetAddressCountry:
    def test_requires_admin(self, client):
        r = client.post("/api/addresses/1/country", json={"countries": ["FR"]})
        assert r.status_code in (401, 403)

    def test_404_missing_address(self, auth_client):
        r = auth_client.post("/api/addresses/999999999/country", json={"countries": ["FR"]})
        assert r.status_code == 404

    def test_400_unknown_country_code(self, auth_client):
        addr = _seed_address("Set country bad")
        r = auth_client.post(f"/api/addresses/{addr}/country", json={"countries": ["ZZ"]})
        assert r.status_code == 400

    def test_ok_with_valid_country(self, auth_client):
        addr = _seed_address("Set country ok")
        r = auth_client.post(f"/api/addresses/{addr}/country", json={"countries": ["FR"]})
        assert r.status_code == 200

    def test_set_country_visible_immediately(self, auth_client):
        # Régression (chantier commit-avant-réponse) : la donnée écrite par le POST
        # est lisible dès le GET suivant. Garde-fou de la dépendance commit-as-you-go
        # et du futur passage du teardown en rollback — un handler d'écriture sans
        # `commit()` ferait alors échouer ce test.
        addr = _seed_address("Readback marker QWXZ")
        r = auth_client.post(f"/api/addresses/{addr}/country", json={"countries": ["FR"]})
        assert r.status_code == 200
        r2 = auth_client.get("/api/addresses/countries", params={"search": "QWXZ"})
        assert r2.status_code == 200
        rows = [a for a in r2.json()["addresses"] if a["id"] == addr]
        assert rows and rows[0]["countries"] == ["fr"]


# ── POST /api/addresses/batch-country ────────────────────────────


class TestBatchSetCountry:
    def test_requires_admin(self, client):
        r = client.post("/api/addresses/batch-country", json={"country_code": "FR"})
        assert r.status_code in (401, 403)

    def test_400_missing_country_code(self, auth_client):
        r = auth_client.post("/api/addresses/batch-country", json={"country_code": ""})
        assert r.status_code == 400

    def test_400_unknown_country_code(self, auth_client):
        r = auth_client.post("/api/addresses/batch-country", json={"country_code": "ZZ"})
        assert r.status_code == 400

    def test_ok_with_ids(self, auth_client):
        a = _seed_address("Batch country ids")
        r = auth_client.post(
            "/api/addresses/batch-country",
            json={"country_code": "FR", "address_ids": [a]},
        )
        assert r.status_code == 200
        body = r.json()
        assert "updated" in body and "propagated" in body

    def test_ok_with_filter(self, auth_client):
        _seed_address("Unique search target for batch")
        r = auth_client.post(
            "/api/addresses/batch-country",
            json={"country_code": "FR", "search": "Unique search target"},
        )
        assert r.status_code == 200

    def test_400_empty_filter(self, auth_client):
        """Ni IDs ni filtre → 400 (garde-fou contre l'application en masse)."""
        r = auth_client.post(
            "/api/addresses/batch-country",
            json={"country_code": "FR"},
        )
        assert r.status_code == 400


# ── GET /api/addresses/stats ─────────────────────────────────


class TestAdminAddressStats:
    def test_default_uses_perimeter(self, client):
        r = client.get("/api/addresses/stats")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) >= {"total", "detected", "pending", "rejected", "confirmed"}

    def test_with_structure_id(self, client):
        struct = _seed_structure("LAB-STATS")
        r = client.get("/api/addresses/stats", params={"structure_id": struct})
        assert r.status_code == 200
