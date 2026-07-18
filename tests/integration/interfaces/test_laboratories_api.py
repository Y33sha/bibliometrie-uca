"""Tests de caractérisation pour le router laboratories.

Les quatre lectures d'un laboratoire s'exercent sur une base vide : ce qu'on
vérifie ici, c'est que chaque chemin est servi et que le SQL passe, non le
contenu des agrégats.
"""


class TestLaboratoriesList:
    def test_returns_list(self, client):
        r = client.get("/api/laboratories")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestLaboratoryDetail:
    def test_unknown_lab_404(self, client):
        r = client.get("/api/laboratories/999999999")
        assert r.status_code == 404


class TestLaboratoryAddresses:
    def test_paginated(self, client):
        r = client.get("/api/laboratories/999999999/addresses", params={"page": 1, "per_page": 10})
        assert r.status_code == 200
        body = r.json()
        assert body["page"] == 1
        assert body["per_page"] == 10
        assert "pages" in body

    def test_rejects_per_page_above_ceiling(self, client):
        r = client.get("/api/laboratories/1/addresses", params={"per_page": 500})
        assert r.status_code == 422


class TestLaboratoryDashboard:
    def test_returns_dashboard(self, client):
        r = client.get("/api/laboratories/999999999/dashboard")
        assert r.status_code == 200


class TestLaboratorySubjects:
    def test_empty_without_publication(self, client):
        r = client.get("/api/laboratories/999999999/subjects")
        assert r.status_code == 200
        assert r.json() == []

    def test_honours_limit(self, client):
        r = client.get("/api/laboratories/999999999/subjects", params={"limit": 5})
        assert r.status_code == 200
