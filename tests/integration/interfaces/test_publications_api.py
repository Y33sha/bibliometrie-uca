"""Tests de caractérisation pour le router publications.

Stratégie : pas de données seedées (la base est vide), on vérifie que
chaque combinaison de filtres exerce le SQL sans crash et renvoie une
réponse structurellement correcte.

Chaque test exerce une branche différente des apply_*_filter et de la
construction dynamique des WHERE/ORDER BY — si le refactor casse un
chemin SQL, ces tests le révèlent par un 500 (via raise_server_exceptions).
"""


class TestPublicationsList:
    """Exerce le SQL de GET /api/publications avec toutes les combinaisons
    de filtres actuellement supportés par le router."""

    def test_empty_list(self, client):
        r = client.get("/api/publications")
        assert r.status_code == 200
        data = r.json()
        assert data["publications"] == []
        assert data["total"] == 0

    def test_pagination_params(self, client):
        r = client.get("/api/publications", params={"page": 2, "per_page": 50})
        assert r.status_code == 200
        assert "page" in r.json() or "publications" in r.json()

    def test_filter_by_single_year(self, client):
        r = client.get("/api/publications", params={"year": 2024})
        assert r.status_code == 200

    def test_filter_by_multiple_years(self, client):
        r = client.get("/api/publications", params={"year": "2023,2024"})
        assert r.status_code == 200

    def test_filter_by_doc_types(self, client):
        r = client.get("/api/publications", params={"doc_type": "article,book"})
        assert r.status_code == 200

    def test_filter_by_oa_status_single(self, client):
        r = client.get("/api/publications", params={"oa_status": "gold"})
        assert r.status_code == 200

    def test_filter_by_oa_status_multiple(self, client):
        r = client.get("/api/publications", params={"oa_status": "gold,green"})
        assert r.status_code == 200

    def test_filter_by_oa_alias(self, client):
        """L'alias 'oa' expanse en (gold, hybrid, bronze, green, diamond)."""
        r = client.get("/api/publications", params={"oa_status": "oa"})
        assert r.status_code == 200

    def test_filter_by_search(self, client):
        r = client.get("/api/publications", params={"search": "quantum"})
        assert r.status_code == 200

    def test_filter_by_labs(self, client):
        r = client.get("/api/publications", params={"lab_id": "1,2,3"})
        assert r.status_code == 200

    def test_filter_lab_none(self, client):
        """Publications UCA sans aucun labo."""
        r = client.get("/api/publications", params={"lab_none": "true"})
        assert r.status_code == 200

    def test_filter_by_person(self, client):
        r = client.get("/api/publications", params={"person_id": 1})
        assert r.status_code == 200

    def test_filter_by_source_present(self, client):
        r = client.get("/api/publications", params={"source": "hal_yes"})
        assert r.status_code == 200

    def test_filter_by_source_absent(self, client):
        r = client.get("/api/publications", params={"source": "oa_no"})
        assert r.status_code == 200

    def test_filter_by_publisher(self, client):
        r = client.get("/api/publications", params={"publisher_id": 1})
        assert r.status_code == 200

    def test_filter_by_journal(self, client):
        r = client.get("/api/publications", params={"journal_id": 1})
        assert r.status_code == 200

    def test_filter_by_subject(self, client):
        r = client.get("/api/publications", params={"subject_id": 1})
        assert r.status_code == 200

    def test_sort_by_year_desc(self, client):
        r = client.get("/api/publications", params={"sort": "year_desc"})
        assert r.status_code == 200

    def test_sort_by_title(self, client):
        r = client.get("/api/publications", params={"sort": "title"})
        assert r.status_code == 200

    def test_complex_filter_combination(self, client):
        """Combine plusieurs filtres pour exercer la construction dynamique
        du WHERE complet — c'est le scénario le plus sensible pour le refactor."""
        r = client.get(
            "/api/publications",
            params={
                "year": "2023,2024",
                "doc_type": "article",
                "oa_status": "oa",
                "lab_id": "1",
                "sort": "year_desc",
                "page": 1,
                "per_page": 20,
            },
        )
        assert r.status_code == 200


class TestPublicationsFacets:
    """Exerce la construction des facettes."""

    def test_facets_structure(self, client):
        r = client.get("/api/publications/facets")
        assert r.status_code == 200
        data = r.json()
        assert "years" in data

    def test_facets_with_filters(self, client):
        """Les facettes doivent refléter le contexte de filtrage."""
        r = client.get(
            "/api/publications/facets",
            params={"year": "2024", "doc_type": "article"},
        )
        assert r.status_code == 200


class TestPublicationsExports:
    """Exports CSV/JSON — génèrent des réponses non-JSON."""

    def test_csv_export(self, client):
        r = client.get("/api/publications/export.csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_csv_export_with_filters(self, client):
        r = client.get(
            "/api/publications/export.csv",
            params={"year": "2024", "doc_type": "article"},
        )
        assert r.status_code == 200


class TestPublicationDetail:
    def test_not_found(self, client):
        r = client.get("/api/publications/999999999")
        assert r.status_code == 404

    def test_invalid_id(self, client):
        r = client.get("/api/publications/abc")
        assert r.status_code in (400, 422)
