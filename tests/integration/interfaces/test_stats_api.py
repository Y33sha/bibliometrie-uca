"""Tests de caractérisation pour le router stats.

Ces endpoints concentrent du SQL complexe (agrégations, facettes
dynamiques).
"""


class TestStatsByYear:
    def test_basic(self, client):
        r = client.get("/api/stats/by-year")
        assert r.status_code == 200

    def test_with_lab_filter(self, client):
        r = client.get("/api/stats/by-year", params={"lab_id": "1"})
        assert r.status_code == 200

    def test_with_doc_type_filter(self, client):
        r = client.get("/api/stats/by-year", params={"doc_type": "article"})
        assert r.status_code == 200


class TestStatsPublishers:
    def test_basic(self, client):
        r = client.get("/api/stats/publishers")
        assert r.status_code == 200

    def test_with_year(self, client):
        r = client.get("/api/stats/publishers", params={"year": "2024"})
        assert r.status_code == 200

    def test_with_oa_status(self, client):
        r = client.get("/api/stats/publishers", params={"oa_status": "gold"})
        assert r.status_code == 200


class TestStatsJournals:
    def test_basic(self, client):
        r = client.get("/api/stats/journals")
        assert r.status_code == 200

    def test_with_filters(self, client):
        r = client.get(
            "/api/stats/journals",
            params={"year": "2024", "oa_status": "oa"},
        )
        assert r.status_code == 200


class TestStatsLabs:
    def test_basic(self, client):
        r = client.get("/api/stats/labs")
        assert r.status_code == 200

    def test_with_year(self, client):
        r = client.get("/api/stats/labs", params={"year": "2024"})
        assert r.status_code == 200


class TestStatsFacets:
    def test_facets(self, client):
        r = client.get("/api/stats/facets")
        assert r.status_code == 200

    def test_facets_with_filter(self, client):
        r = client.get("/api/stats/facets", params={"year": "2024"})
        assert r.status_code == 200


class TestStatsYears:
    def test_years_list(self, client):
        r = client.get("/api/stats/years")
        assert r.status_code == 200
