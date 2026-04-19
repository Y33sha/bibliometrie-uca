"""Tests de caractérisation pour le router persons (§1.1).

Stratégie identique à test_publications_api.py : exercer les branches
de filtrage avec une base vide, pour verrouiller le comportement avant
l'extraction du SQL vers des repositories.
"""


class TestPersonsList:
    def test_empty_list(self, client):
        r = client.get("/api/persons")
        assert r.status_code == 200
        data = r.json()
        assert "persons" in data
        assert "total" in data

    def test_pagination(self, client):
        r = client.get("/api/persons", params={"page": 2, "per_page": 20})
        assert r.status_code == 200

    def test_filter_by_search(self, client):
        r = client.get("/api/persons", params={"search": "dupont"})
        assert r.status_code == 200

    def test_filter_by_department(self, client):
        r = client.get("/api/persons", params={"department": "Informatique"})
        assert r.status_code == 200

    def test_filter_by_role(self, client):
        r = client.get("/api/persons", params={"role": "Enseignant-chercheur"})
        assert r.status_code == 200

    def test_filter_by_has_orcid_yes(self, client):
        r = client.get("/api/persons", params={"has_orcid": "yes"})
        assert r.status_code == 200

    def test_filter_by_has_orcid_no(self, client):
        r = client.get("/api/persons", params={"has_orcid": "no"})
        assert r.status_code == 200

    def test_sort_by_name(self, client):
        r = client.get("/api/persons", params={"sort": "last_name"})
        assert r.status_code == 200

    def test_complex_filter(self, client):
        r = client.get(
            "/api/persons",
            params={
                "search": "test",
                "department": "Maths",
                "has_orcid": "yes",
                "page": 1,
                "per_page": 50,
            },
        )
        assert r.status_code == 200


class TestPersonsFacets:
    def test_facets_structure(self, client):
        r = client.get("/api/persons/facets")
        assert r.status_code == 200

    def test_facets_with_filters(self, client):
        r = client.get("/api/persons/facets", params={"department": "Maths"})
        assert r.status_code == 200


class TestPersonsSearch:
    def test_search_empty_query(self, client):
        r = client.get("/api/persons/search", params={"q": ""})
        assert r.status_code in (200, 400, 422)

    def test_search_short_query(self, client):
        """La recherche doit gérer les requêtes courtes sans crash."""
        r = client.get("/api/persons/search", params={"q": "ab"})
        assert r.status_code == 200

    def test_search_special_chars(self, client):
        """Caractères spéciaux (apostrophe, accents) — vérifie l'échappement."""
        r = client.get("/api/persons/search", params={"q": "O'brien"})
        assert r.status_code == 200

    def test_search_accents(self, client):
        r = client.get("/api/persons/search", params={"q": "hervé"})
        assert r.status_code == 200


class TestPersonDirectory:
    def test_directory(self, client):
        r = client.get("/api/persons/directory")
        assert r.status_code == 200


class TestPersonEndpoints:
    def test_departments_list(self, client):
        r = client.get("/api/persons/departments")
        assert r.status_code == 200

    def test_roles_list(self, client):
        r = client.get("/api/persons/roles")
        assert r.status_code == 200

    def test_stats(self, client):
        r = client.get("/api/persons/stats")
        assert r.status_code == 200


class TestPersonDetail:
    def test_not_found(self, client):
        r = client.get("/api/persons/999999999")
        assert r.status_code == 404

    def test_profile_not_found(self, client):
        r = client.get("/api/persons/999999999/profile")
        assert r.status_code == 404

    def test_theses_not_found(self, client):
        r = client.get("/api/persons/999999999/theses")
        assert r.status_code in (200, 404)

    def test_addresses_not_found(self, client):
        r = client.get("/api/persons/999999999/addresses")
        assert r.status_code in (200, 404)
