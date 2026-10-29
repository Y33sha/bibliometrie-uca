"""Tests de caractérisation du router des publications.

Sur une base vide, chaque test exerce une branche des filtres, des tris, des facettes ou des exports, et vérifie la forme de la réponse. Un chemin SQL cassé se révèle par un 500.
"""

import pytest

from domain.publications.licenses import LICENSE_LABELS
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from tests.integration.helpers.db import owner_connection
from tests.integration.helpers.seeds import seed_publication, uniq
from tests.integration.helpers.sources import insert_source_record


def test_licenses_follow_the_domain_enum(client):
    r = client.get("/api/publications/licenses")
    assert r.status_code == 200
    assert [(o["value"], o["label_fr"]) for o in r.json()] == [
        (lic.value, label) for lic, label in LICENSE_LABELS.items()
    ]


def test_sources_are_readable_without_session(client):
    """La route des sources d'une publication répond sans session : une publication inconnue renvoie 404."""
    r = client.get("/api/publications/999999/sources")
    assert r.status_code == 404
    assert r.json()["detail"] == "Publication introuvable"


class TestSuspectMerges:
    """File des fusions suspectes : la lecture de la vue matérialisée passe sous le rôle de l'API."""

    def test_compteur(self, client):
        r = client.get("/api/publications/suspect-merges/count")
        assert r.status_code == 200
        assert r.json() == {"total": 0}

    def test_liste_vide(self, client):
        r = client.get("/api/publications/suspect-merges", params={"page": 1, "per_page": 20})
        assert r.status_code == 200
        assert r.json()["publications"] == []


class TestPublicationsList:
    """SQL de GET /api/publications, sous chaque filtre et chaque tri."""

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

    def test_filter_by_search(self, client):
        r = client.get("/api/publications", params={"search": "quantum"})
        assert r.status_code == 200

    def test_filter_by_labs(self, client):
        r = client.get("/api/publications", params={"lab_id": "1,2,3"})
        assert r.status_code == 200

    def test_filter_lab_none(self, client):
        """Publications sans laboratoire."""
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

    def test_filter_by_serial(self, client):
        r = client.get("/api/publications", params={"serial_id": 1})
        assert r.status_code == 200

    def test_filter_by_subject(self, client):
        r = client.get("/api/publications", params={"subject_id": 1})
        assert r.status_code == 200

    def test_filter_by_several_subjects(self, client):
        r = client.get("/api/publications", params={"subject_id": "1,2"})
        assert r.status_code == 200

    def test_sort_by_year_desc(self, client):
        r = client.get("/api/publications", params={"sort": "year_desc"})
        assert r.status_code == 200

    def test_sort_by_title(self, client):
        r = client.get("/api/publications", params={"sort": "title_asc"})
        assert r.status_code == 200

    def test_sort_by_inscription(self, client):
        """Le tri par date d'inscription de la table des thèses est un tri valide de la liste."""
        r = client.get("/api/publications", params={"sort": "inscription_asc"})
        assert r.status_code == 200

    def test_complex_filter_combination(self, client):
        """Plusieurs filtres combinés exercent la construction complète de la clause WHERE."""
        r = client.get(
            "/api/publications",
            params={
                "year": "2023,2024",
                "doc_type": "article",
                "oa_status": "gold",
                "lab_id": "1",
                "sort": "year_desc",
                "page": 1,
                "per_page": 20,
            },
        )
        assert r.status_code == 200


class TestClosedVocabularyFilters:
    """Une valeur hors vocabulaire est refusée en 422. Ignorée, elle laisserait passer une liste non filtrée sous un code 200."""

    @pytest.mark.parametrize(
        ("param", "value"),
        [
            ("doc_type", "nimportequoi"),
            ("excluded_doc_type", "nimportequoi"),
            ("oa_status", "vert"),
            ("oa_status", "oa"),
            ("access", "ouvert"),
            ("hal_status", "bogus"),
        ],
    )
    def test_refuses_a_value_outside_the_vocabulary(self, client, param, value):
        r = client.get("/api/publications", params={param: value})
        assert r.status_code == 422
        assert value in r.json()["detail"]

    def test_refuses_a_list_where_one_value_is_unknown(self, client):
        r = client.get("/api/publications", params={"doc_type": "article,bogus"})
        assert r.status_code == 422

    def test_accepts_the_embargoed_status(self, client):
        r = client.get("/api/publications", params={"oa_status": "embargoed"})
        assert r.status_code == 200


class TestPublicationsFacets:
    """Construction des facettes, avec et sans filtres."""

    def test_facets_structure(self, client):
        r = client.get("/api/publications/facets")
        assert r.status_code == 200
        data = r.json()
        assert "years" in data

    def test_language_filter_and_facet(self, client):
        r = client.get("/api/publications/facets", params={"language": "en,fr"})
        assert r.status_code == 200
        assert "languages" in r.json()
        r = client.get("/api/publications", params={"language": "en"})
        assert r.status_code == 200

    def test_facets_with_filters(self, client):
        """Facettes calculées sous filtres."""
        r = client.get(
            "/api/publications/facets",
            params={"year": "2024", "doc_type": "article"},
        )
        assert r.status_code == 200

    def test_entity_facet_serial(self, client):
        r = client.get("/api/publications/facets/entities", params={"kind": "serial"})
        assert r.status_code == 200
        assert "entities" in r.json()

    def test_entity_facet_publisher_contextual(self, client):
        # Facette éditeur sous filtres + recherche de nom + corrélation (revue sélectionnée).
        r = client.get(
            "/api/publications/facets/entities",
            params={"kind": "publisher", "entity_search": "els", "year": "2024", "serial_id": "1"},
        )
        assert r.status_code == 200

    def test_entity_facet_person_on_a_person_page(self, client):
        # Facette auteur sous filtres + recherche de nom, sur une page personne avec un auteur choisi.
        r = client.get(
            "/api/publications/facets/entities",
            params={
                "kind": "person",
                "entity_search": "du",
                "year": "2024",
                "person_id": "1",
                "author_id": "2",
            },
        )
        assert r.status_code == 200

    def test_entity_facet_subject_under_a_subject_selection(self, client):
        # Facette des sujets sous sa propre sélection, qu'elle ignore, et sous une recherche de libellé.
        r = client.get(
            "/api/publications/facets/entities",
            params={"kind": "subject", "entity_search": "chim", "subject_id": "1,2"},
        )
        assert r.status_code == 200

    def test_author_filter_applies_to_list_facets_and_export(self, client):
        for path in (
            "/api/publications",
            "/api/publications/facets",
            "/api/publications/export.csv",
        ):
            r = client.get(path, params={"author_id": "1"})
            assert r.status_code == 200, path


class TestPublicationsExports:
    """Export CSV de la liste des publications."""

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

    def test_csv_export_respects_columns(self, client):
        """Le CSV contient les colonnes demandées, puis Titre et Accès, toujours présents."""
        r = client.get("/api/publications/export.csv", params={"columns": "type,year"})
        assert r.status_code == 200
        header = r.text.splitlines()[0].lstrip("﻿").split(",")
        assert header == ["Type", "Année", "Titre", "Accès"]

    def test_csv_export_publisher_is_its_own_column(self, client):
        """La colonne de l'éditeur est distincte de celle de la revue."""
        r = client.get("/api/publications/export.csv", params={"columns": "publisher"})
        assert r.status_code == 200
        header = r.text.splitlines()[0].lstrip("﻿").split(",")
        assert "Éditeur" in header
        assert "Revue" not in header
        r = client.get("/api/publications/export.csv", params={"columns": "serial"})
        assert "Éditeur" not in r.text.splitlines()[0]

    def test_csv_export_hal_status_column(self, client):
        """Sur une page de laboratoire, la colonne du statut HAL s'exporte."""
        r = client.get(
            "/api/publications/export.csv",
            params={"columns": "hal_status", "lab_id": "1", "hal_status": "ok,notice"},
        )
        assert r.status_code == 200
        assert "Statut HAL" in r.text.splitlines()[0]

    def test_hal_status_facet_and_filter_on_a_lab(self, client):
        r = client.get("/api/publications/facets", params={"lab_id": "1", "hal_status": "hors_hal"})
        assert r.status_code == 200
        assert [o["value"] for o in r.json()["hal_status"]] == [
            "ok",
            "notice",
            "hors_collection",
            "hors_hal",
        ]

    def test_csv_export_is_streamed(self, client):
        """La réponse part en flux, sans composer le fichier entier en mémoire."""
        with client.stream("GET", "/api/publications/export.csv") as r:
            assert r.status_code == 200
            assert "content-length" not in r.headers  # taille inconnue à l'envoi
            assert next(r.iter_raw())  # le premier bloc part sans attendre le dernier

    def test_csv_export_opens_with_a_byte_order_mark(self, client):
        """Sans BOM, un tableur lit l'UTF-8 comme de l'ANSI et altère les accents."""
        r = client.get("/api/publications/export.csv")
        assert r.text.startswith("\ufeff")


class TestThesesExport:
    def test_csv_export(self, client):
        r = client.get("/api/publications/export-theses.csv")
        assert r.status_code == 200

    def test_csv_export_is_streamed(self, client):
        with client.stream("GET", "/api/publications/export-theses.csv") as r:
            assert r.status_code == 200
            assert "content-length" not in r.headers
            assert "theses.csv" in r.headers.get("content-disposition", "")
        assert "text/csv" in r.headers.get("content-type", "")

    def test_csv_export_with_filters(self, client):
        r = client.get(
            "/api/publications/export-theses.csv",
            params={"year": "2024", "lab_id": "1", "sort": "soutenance_asc"},
        )
        assert r.status_code == 200

    def test_csv_export_narrows_to_given_doc_type(self, client):
        """Sans `doc_type`, l'export porte sur les thèses soutenues et en cours ; avec, sur le seul type demandé."""
        r = client.get("/api/publications/export-theses.csv", params={"doc_type": "thesis"})
        assert r.status_code == 200


class TestPublicationDetail:
    def test_not_found(self, client):
        r = client.get("/api/publications/999999999")
        assert r.status_code == 404

    def test_invalid_id(self, client):
        r = client.get("/api/publications/abc")
        assert r.status_code in (400, 422)


class TestPublicationSources:
    def test_not_found(self, client):
        r = client.get("/api/publications/999999999/sources")
        assert r.status_code == 404

    def test_doi_affiche_par_role_et_autres_doi_parmi_les_identifiants(self, client):
        """Régression : le DOI affiché d'un enregistrement ScanR était son DOI `secondary` (preprint), et non son DOI `derived`."""
        publication_id = seed_publication("Article")
        with owner_connection() as conn:
            insert_source_record(
                conn,
                publication_id,
                source="scanr",
                source_id=uniq("doi10.1038/s41598-1"),
                title="Article",
                identifiers=[
                    SourceIdentifier(
                        SourceIdentifierType.DOI, "10.1038/s41598-1", SourceIdentifierRole.DERIVED
                    ),
                    SourceIdentifier(
                        SourceIdentifierType.DOI,
                        "10.21203/rs.3.rs-1",
                        SourceIdentifierRole.SECONDARY,
                    ),
                    SourceIdentifier(
                        SourceIdentifierType.DOI,
                        "10.9999/faux",
                        SourceIdentifierRole.SECONDARY,
                        "UNRESOLVED_DOI_TO_NULL",
                    ),
                ],
            )
        r = client.get(f"/api/publications/{publication_id}/sources")
        assert r.status_code == 200
        [record] = r.json()["source_records"]
        assert record["doi"] == "10.1038/s41598-1"
        assert record["identifiers"] == [{"type": "doi", "value": "10.21203/rs.3.rs-1"}]
