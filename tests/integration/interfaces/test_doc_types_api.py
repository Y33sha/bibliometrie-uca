"""Tests du router /api/doc-types — expose les libellés FR canoniques."""

from domain.publications.doc_types import DOC_TYPE_LABELS_FR


class TestListDocTypes:
    def test_returns_all_doc_types(self, client):
        r = client.get("/api/doc-types")
        assert r.status_code == 200
        body = r.json()
        items = body["items"]
        assert {item["value"] for item in items} == set(DOC_TYPE_LABELS_FR.keys())

    def test_singular_plural_present(self, client):
        r = client.get("/api/doc-types")
        for item in r.json()["items"]:
            assert item["singular"]
            assert item["plural"]

    def test_thesis_label(self, client):
        r = client.get("/api/doc-types")
        item = next(it for it in r.json()["items"] if it["value"] == "thesis")
        assert item["singular"] == "Thèse"
        assert item["plural"] == "Thèses"
