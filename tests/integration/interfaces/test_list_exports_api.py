"""Exports CSV des listes : chaque liste sert un CSV dont l'en-tête reprend les colonnes de son tableau."""

import csv
import io

import pytest

from tests.integration.helpers.seeds import seed_structure, uniq

BOM = "﻿"


def _rows(text: str) -> list[list[str]]:
    assert text.startswith(BOM)
    return list(csv.reader(io.StringIO(text.removeprefix(BOM))))


@pytest.mark.parametrize(
    ("path", "params", "header"),
    [
        (
            "/api/publishers/export.csv",
            {"sort": "publications_desc"},
            ["Nom", "Type", "Pays", "Préfixes DOI", "Publications en série", "Publications"],
        ),
        (
            "/api/serials/export.csv",
            {"has_publications": "true"},
            ["Titre", "ISSN", "Éditeur", "Type", "DOAJ", "Publications"],
        ),
        (
            "/api/monographs/export.csv",
            {"type": "book"},
            ["Titre", "Type", "Année", "ISBN", "Éditeur", "Collection", "Publications"],
        ),
        (
            "/api/persons/export.csv",
            {"exclusion": "none", "active": "true"},
            [
                "Nom",
                "Prénom",
                "RH",
                "ORCID",
                "idHAL",
                "IdRef",
                "Fonction",
                "Département",
                "Publications",
            ],
        ),
        (
            "/api/subjects/export.csv",
            {"min_count": "3"},
            ["Libellé", "Langue", "Occurrences"],
        ),
        (
            "/api/structures/export.csv",
            {"structure_type": "labo"},
            ["Type", "Acronyme", "Nom", "Tutelles", "ROR", "Collection HAL"],
        ),
        (
            "/api/hal-problems/duplicate-accounts/export.csv",
            {},
            [
                "Nom",
                "Prénom",
                "RH",
                "Compte HAL",
                "Nom HAL",
                "Publications",
                "idHAL",
                "ORCID",
                "IdRef",
            ],
        ),
        (
            "/api/hal-problems/duplicate-publications-doi/export.csv",
            {},
            ["DOI", "Année", "Type", "Titre", "Dépôts HAL"],
        ),
        (
            "/api/hal-problems/duplicate-publications-meta/export.csv",
            {},
            ["Année", "Type", "Titre A", "Dépôts HAL A", "Titre B", "Dépôts HAL B"],
        ),
        (
            "/api/hal-problems/affiliation-conflicts/export.csv",
            {},
            ["Année", "Type", "Titre", "DOI", "Dépôts HAL", "Laboratoires"],
        ),
    ],
)
def test_serves_a_csv_with_the_table_columns(client, path, params, header):
    r = client.get(path, params=params)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert _rows(r.text)[0] == header


@pytest.mark.parametrize(
    "path",
    [
        "/api/publishers/export.csv",
        "/api/serials/export.csv",
        "/api/monographs/export.csv",
        "/api/persons/export.csv",
    ],
)
def test_rejects_an_unknown_sort(client, path):
    assert client.get(path, params={"sort": "nimportequoi"}).status_code == 422


class TestMissingCollectionsExport:
    def test_unknown_lab_is_404(self, client):
        r = client.get(
            "/api/hal-problems/missing-collections/export.csv", params={"lab_id": 999_999_999}
        )
        assert r.status_code == 404

    def test_lab_without_collection_is_422(self, client):
        lab_id = seed_structure(code=uniq("NOCOL"))
        r = client.get(
            "/api/hal-problems/missing-collections/export.csv", params={"lab_id": lab_id}
        )
        assert r.status_code == 422

    def test_lab_with_collection_serves_a_csv(self, client):
        lab_id = seed_structure(code=uniq("COL"), hal_collection=uniq("col"))
        r = client.get(
            "/api/hal-problems/missing-collections/export.csv", params={"lab_id": lab_id}
        )
        assert r.status_code == 200
        assert _rows(r.text)[0] == ["Année", "Type", "Titre", "DOI", "Dépôts HAL"]


def test_exports_the_filtered_rows(client):
    code = uniq("EXPORT")
    seed_structure(code=code, name="Structure à exporter")
    rows = _rows(client.get("/api/structures/export.csv", params={"search": code}).text)
    assert [row[2] for row in rows[1:]] == ["Structure à exporter"]
