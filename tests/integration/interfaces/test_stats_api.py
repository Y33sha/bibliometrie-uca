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


class TestCollaborations:
    def test_returns_country_counts(self, client):
        r = client.get("/api/stats/collaborations")
        assert r.status_code == 200
        assert {"rows", "total_count", "international_count"} <= set(r.json())

    def test_honours_filters(self, client):
        r = client.get("/api/stats/collaborations", params={"year": "2024", "oa_status": "gold"})
        assert r.status_code == 200


class TestPivot:
    def test_schema_lists_dimensions_and_measures(self, client):
        r = client.get("/api/stats/pivot/schema")
        assert r.status_code == 200
        body = r.json()
        assert body["dimensions"]
        assert body["measures"]

    def test_default_measure_without_grouping(self, client):
        r = client.get("/api/stats/pivot")
        assert r.status_code == 200

    def test_single_grouping(self, client):
        r = client.get("/api/stats/pivot", params={"measure": "pub_count", "group": "year"})
        assert r.status_code == 200

    def test_double_grouping(self, client):
        r = client.get("/api/stats/pivot", params={"group": "year", "group2": "doc_type_grouped"})
        assert r.status_code == 200

    def test_rejects_a_dimension_that_is_not_groupable(self, client):
        """`doc_type` se filtre mais ne se ventile pas ; `doc_type_grouped` est sa forme groupable."""
        r = client.get("/api/stats/pivot", params={"group": "doc_type"})
        assert r.status_code == 400

    def test_rejects_second_grouping_without_the_first(self, client):
        r = client.get("/api/stats/pivot", params={"group2": "year"})
        assert r.status_code == 400

    def test_rejects_unknown_measure(self, client):
        r = client.get("/api/stats/pivot", params={"measure": "inexistante"})
        assert r.status_code == 400

    def test_rejects_repeated_grouping(self, client):
        r = client.get("/api/stats/pivot", params={"group": "year", "group2": "year"})
        assert r.status_code == 400
