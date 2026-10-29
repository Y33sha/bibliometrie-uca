"""Tests de caractérisation du router des statistiques : collaborations, tableau croisé et ses filtres."""

import pytest


class TestCollaborations:
    def test_returns_country_counts(self, client):
        r = client.get("/api/stats/collaborations")
        assert r.status_code == 200
        assert {"rows", "total_count", "international_count"} <= set(r.json())

    def test_honours_filters(self, client):
        r = client.get("/api/stats/collaborations", params={"year": "2024", "oa_status": "gold"})
        assert r.status_code == 200


class TestPivot:
    def test_schema_lists_dimensions_and_indicators(self, client):
        r = client.get("/api/stats/pivot/schema")
        assert r.status_code == 200
        body = r.json()
        assert body["dimensions"]
        apc = next(i for i in body["indicators"] if i["key"] == "apc_amount")
        assert apc["unit"] == "€ HT"

    def test_default_indicator(self, client):
        r = client.get("/api/stats/pivot")
        assert r.status_code == 200
        assert r.json()["groups"] == ["doc_type_grouped"]

    def test_indicator_with_comparison(self, client):
        r = client.get("/api/stats/pivot", params={"indicator": "apc_amount", "compare": "year"})
        assert r.status_code == 200
        body = r.json()
        assert body["measure"] == "apc_amount"
        assert body["groups"] == ["oa_voie", "year"]

    def test_rejects_unknown_indicator(self, client):
        r = client.get("/api/stats/pivot", params={"indicator": "inexistant"})
        assert r.status_code == 422

    def test_rejects_a_dimension_that_is_not_comparable(self, client):
        r = client.get("/api/stats/pivot", params={"compare": "oa_access"})
        assert r.status_code == 422


class TestStatsAcceptListFilters:
    """Les statistiques lisent les filtres de la liste, sauf ceux qui supposent un seul laboratoire ou une personne."""

    @pytest.mark.parametrize(
        ("param", "value"),
        [("access", "inconnu"), ("source_filter", "inconnu"), ("subject_id", "x")],
    )
    def test_reads_list_filters(self, client, param, value):
        r = client.get("/api/stats/pivot", params={param: value})
        assert r.status_code == 422

    def test_accepts_search_country_and_author(self, client):
        params = {"search": "quantum", "country": "de", "author_id": "1", "lab_id": "none"}
        assert client.get("/api/stats/pivot", params=params).status_code == 200

    @pytest.mark.parametrize("param", ["hal_status", "is_corresponding", "in_perimeter"])
    def test_ignores_context_filters(self, client, param):
        r = client.get("/api/stats/pivot", params={param: "inconnu"})
        assert r.status_code == 200


class TestStatsClosedVocabularyFilters:
    """Les filtres partagés `oa_status` et `doc_type` refusent une valeur hors vocabulaire.

    Même contrat que la liste des publications : une valeur hors vocabulaire renvoie 422. `oa`, absent des statuts stockés, est refusé aussi.
    """

    @pytest.mark.parametrize(
        ("param", "value"),
        [
            ("oa_status", "vert"),
            ("oa_status", "oa"),
            ("doc_type", "nimportequoi"),
        ],
    )
    def test_refuses_a_value_outside_the_vocabulary(self, client, param, value):
        r = client.get("/api/stats/pivot", params={param: value})
        assert r.status_code == 422
        assert value in r.json()["detail"]
