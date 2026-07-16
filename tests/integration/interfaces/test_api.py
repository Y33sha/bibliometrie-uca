"""Tests smoke des endpoints API : vérifient que chaque endpoint principal
répond sans crash sur une base vide.

Les tests de caractérisation avec données seedées sont dans les fichiers
`test_<router>_api.py` dédiés.

Fixtures `client` et `auth_client` viennent de `conftest.py`.
"""


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
        r = client.get("/api/laboratories")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_not_found(self, client):
        r = client.get("/api/laboratories/999999999")
        assert r.status_code in (404, 500)


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


class TestConfig:
    def test_get_config(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200

    def test_write_requires_auth(self, client):
        """Les écritures config sans auth renvoient 401."""
        r = client.post("/api/perimeters/1/structures", json={"structure_id": 1})
        assert r.status_code == 401


# ── Adresses ────────────────────────────────────────────────────


class TestAddresses:
    def test_countries(self, client):
        r = client.get("/api/countries")
        assert r.status_code == 200
