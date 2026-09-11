"""Tests d'intégration de `GET /api/config/institution` : nom et racines du périmètre des personnes."""

from __future__ import annotations

import json

import pytest

from tests.integration.helpers.db import owner_pool


def _seed_structure(code: str) -> int:
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (%s, %s, 'universite') RETURNING id",
            (code, code),
        )
        return cur.fetchone()["id"]


def _seed_perimeter(code: str, name: str, root_structure_ids: list[int]) -> None:
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO perimeters (code, name, root_structure_ids) VALUES (%s, %s, %s)",
            (code, name, root_structure_ids),
        )


def _set_persons_perimeter(code: str) -> None:
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', CAST(%s AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (json.dumps(code),),
        )


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    with owner_pool() as cur:
        cur.execute("TRUNCATE TABLE perimeters, structures, config RESTART IDENTITY CASCADE")


def test_serves_name_and_roots_of_persons_perimeter(client):
    root = _seed_structure("inst_root")
    _seed_perimeter("inst", "Université Test", [root])
    _set_persons_perimeter("inst")

    r = client.get("/api/config/institution")

    assert r.status_code == 200
    assert r.json() == {"name": "Université Test", "root_structure_ids": [root]}


def test_falls_back_to_code_without_perimeter_row(client):
    _set_persons_perimeter("sans_ligne")

    r = client.get("/api/config/institution")

    assert r.status_code == 200
    assert r.json() == {"name": "sans_ligne", "root_structure_ids": []}
