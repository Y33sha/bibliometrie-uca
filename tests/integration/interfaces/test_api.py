"""Tests smoke des endpoints API : vérifient que chaque endpoint principal
répond sans crash sur une base vide.

Les tests de caractérisation avec données seedées sont dans les fichiers
`test_<router>_api.py` dédiés.

Fixtures `client` et `auth_client` viennent de `conftest.py`.
"""

import pytest
from sqlalchemy import text

from domain.config import PUBLIC_CONFIG_KEYS
from infrastructure.db.engine import get_sync_engine

CREDENTIAL_CONFIG_KEYS = frozenset(
    {"openalex_api_key", "wos_api_key", "scanr_username", "scanr_password", "polite_pool_email"}
)


@pytest.fixture
def config_keys_seeded():
    """Pose dans `config` chaque clé publique et chaque identifiant d'accès, puis retire ce qu'elle a posé.

    Sans cette pose, une lecture qui ne rend aucun identifiant ne prouve rien : la base de test n'en porte pas. Les lectures de l'API passent par leur propre connexion, d'où une pose committée, reprise clé par clé.
    """
    keys = [*PUBLIC_CONFIG_KEYS, *CREDENTIAL_CONFIG_KEYS]
    with get_sync_engine().begin() as conn:
        added = [
            k
            for k in keys
            if conn.execute(
                text(
                    "INSERT INTO config (key, value) VALUES (:k, to_jsonb('x'::text)) "
                    "ON CONFLICT (key) DO NOTHING RETURNING key"
                ),
                {"k": k},
            ).scalar_one_or_none()
        ]
    yield
    if added:
        with get_sync_engine().begin() as conn:
            conn.execute(text("DELETE FROM config WHERE key = ANY(:ks)"), {"ks": added})


# ── Publications ────────────────────────────────────────────────


class TestPublications:
    def test_list(self, client):
        r = client.get("/api/publications")
        assert r.status_code == 200
        data = r.json()
        assert "publications" in data
        assert "total" in data

    def test_facets(self, client):
        r = client.get("/api/publications/facets")
        assert r.status_code == 200
        data = r.json()
        assert "years" in data

    def test_not_found(self, client):
        r = client.get("/api/publications/999999999")
        assert r.status_code == 404


# ── Personnes ───────────────────────────────────────────────────


class TestPersons:
    def test_list(self, client):
        r = client.get("/api/persons")
        assert r.status_code == 200
        data = r.json()
        assert "persons" in data
        assert "total" in data

    def test_facets(self, client):
        r = client.get("/api/persons/facets")
        assert r.status_code == 200

    def test_search(self, client):
        r = client.get("/api/persons/search", params={"q": "dupont"})
        assert r.status_code == 200

    def test_not_found(self, client):
        r = client.get("/api/persons/999999999")
        assert r.status_code == 404


# ── Laboratoires ────────────────────────────────────────────────


class TestLaboratories:
    def test_list(self, client):
        r = client.get("/api/structures", params={"in_perimeter": "true", "type": "labo"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_not_found(self, client):
        r = client.get("/api/structures/999999999")
        assert r.status_code == 404


# ── Auth ────────────────────────────────────────────────────────


class TestAuth:
    def test_check_unauthenticated(self, client):
        r = client.get("/api/auth/check")
        assert r.status_code == 200
        assert r.json()["authenticated"] is False

    def test_write_requires_auth(self, client):
        """Les POST sans cookie session renvoient 401."""
        r = client.post("/api/persons/999999999/merge", json={"target_id": 1})
        assert r.status_code == 401

    def test_write_with_auth(self, auth_client):
        """Avec un cookie valide, le POST passe (même si 404 ou 400)."""
        r = auth_client.post("/api/persons/999999999/merge", json={"target_id": 1})
        assert r.status_code != 401


# ── Config ──────────────────────────────────────────────────────


class TestApiBoundary:
    def test_unknown_api_path_is_not_served_by_the_frontend(self, client):
        """Le frontend est monté en dernier et reçoit tout ce qu'aucun router n'a pris : sous `/api`, il doit rendre la main plutôt que sa page d'accueil."""
        r = client.get("/api/chemin-qui-n-existe-pas")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")


class TestConfig:
    def test_get_config(self, auth_client):
        r = auth_client.get("/api/config")
        assert r.status_code == 200

    def test_read_without_session_hides_the_credentials(self, client, config_keys_seeded):
        """Aucun identifiant d'accès aux sources ne sort d'une lecture sans session."""
        r = client.get("/api/config")
        assert r.status_code == 200
        assert {item["key"] for item in r.json()}.isdisjoint(CREDENTIAL_CONFIG_KEYS)

    def test_read_without_session_renders_exactly_the_whitelist(self, client, config_keys_seeded):
        """Sur une table portant chaque clé publique et chaque identifiant, la lecture sans session rend la liste blanche, et elle entière.

        Le sens strict compte des deux côtés : une clé réservée qui sortirait est une fuite, une clé publique retenue est une page qui se vide.
        """
        r = client.get("/api/config")
        assert {item["key"] for item in r.json()} == set(PUBLIC_CONFIG_KEYS)

    def test_write_requires_auth(self, client):
        """Les écritures config sans session renvoient 401."""
        r = client.put("/api/config/pipeline_start_year_full", json={"value": 2020})
        assert r.status_code == 401


# ── Adresses ────────────────────────────────────────────────────


class TestAddresses:
    def test_countries(self, client):
        r = client.get("/api/countries")
        assert r.status_code == 200
