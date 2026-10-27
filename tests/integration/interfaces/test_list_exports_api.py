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


def test_exports_the_filtered_rows(client):
    code = uniq("EXPORT")
    seed_structure(code=code, name="Structure à exporter")
    rows = _rows(client.get("/api/structures/export.csv", params={"search": code}).text)
    assert [row[2] for row in rows[1:]] == ["Structure à exporter"]
