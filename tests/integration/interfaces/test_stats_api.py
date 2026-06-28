"""Tests de caractérisation pour le router stats.

Ces endpoints concentrent du SQL complexe (agrégations, facettes
dynamiques).
"""


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
