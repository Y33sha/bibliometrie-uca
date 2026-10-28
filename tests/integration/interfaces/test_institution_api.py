"""Tests d'intégration de `GET /api/config/institution` : nom et racines du périmètre des personnes, titre de l'application."""

from __future__ import annotations

import pytest

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import seed_config, seed_perimeter, seed_structure


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with owner_pool() as cur:
        cur.execute("TRUNCATE TABLE perimeters, structures RESTART IDENTITY CASCADE")
        # Seule la clé posée par les tests part : les autres viennent de la migration.
        cur.execute("DELETE FROM config WHERE key = 'perimeter_persons'")
        cur.execute("""UPDATE config SET value = '""' WHERE key = 'site_title'""")


def test_serves_name_and_roots_of_persons_perimeter(client):
    root = seed_structure("inst_root", type_="universite")
    seed_perimeter("inst", [root], name="Université Test")
    seed_config("perimeter_persons", "inst")

    r = client.get("/api/config/institution")

    assert r.status_code == 200
    assert r.json() == {"name": "Université Test", "root_structure_ids": [root], "title": None}


def test_falls_back_to_code_without_perimeter_row(client):
    seed_config("perimeter_persons", "sans_ligne")

    r = client.get("/api/config/institution")

    assert r.status_code == 200
    assert r.json() == {"name": "sans_ligne", "root_structure_ids": [], "title": None}


def test_serves_site_title(client):
    seed_config("site_title", "Observatoire des publications")

    r = client.get("/api/config/institution")

    assert r.json()["title"] == "Observatoire des publications"
