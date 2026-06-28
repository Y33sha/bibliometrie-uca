"""Tests de caractérisation pour le router stats.

Ces endpoints concentrent du SQL complexe (agrégations, facettes
dynamiques).
"""


class TestStatsEntityFacet:
    def test_journal(self, client):
        r = client.get("/api/stats/facets/entities", params={"kind": "journal"})
        assert r.status_code == 200

    def test_publisher_with_search_and_filters(self, client):
        r = client.get(
            "/api/stats/facets/entities",
            params={"kind": "publisher", "entity_search": "els", "year": "2024", "journal_id": "1"},
        )
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
