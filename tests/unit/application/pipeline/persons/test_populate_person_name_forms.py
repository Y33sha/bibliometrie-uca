"""Tests unitaires de `populate_person_name_forms.populate`.

Mocks : port `NameFormsQueries`, `Connection` (commit), logger. Pas de DB.

L'orchestrateur calcule les formes de noms en Python via `compute_person_name_forms` (déjà testé côté domain) puis insère par batches dans une table temp avant un sync SQL final.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from application.pipeline.persons import populate_person_name_forms
from application.pipeline.persons.populate_person_name_forms import BATCH_SIZE, populate


class _FakeQueries:
    def __init__(self, persons_rows: list[dict[str, Any]]) -> None:
        self._persons_rows = persons_rows
        self.create_temp_called = False
        self.drop_temp_called = False
        self.batches: list[list[dict[str, object]]] = []
        self.sync_return = (0, 0, 0)
        self.sync_called = False

    def fetch_persons_names(self, conn: object) -> list[dict[str, Any]]:
        return self._persons_rows

    def create_temp_raw_forms_table(self, conn: object) -> None:
        self.create_temp_called = True

    def insert_raw_forms_batch(self, conn: object, rows: list[dict[str, Any]]) -> None:
        # Snapshot par copie : le code source réutilise la liste `batch` en la réaffectant à `[]`, donc une référence directe serait OK, mais on copie pour figer le contenu vu à l'appel.
        self.batches.append(list(rows))

    def drop_temp_raw_forms_table(self, conn: object) -> None:
        self.drop_temp_called = True

    def sync_from_raw_forms(self, conn: object) -> tuple[int, int, int]:
        self.sync_called = True
        return self.sync_return


class _FakeConn:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_populate_person_name_forms")


def test_empty_persons_still_creates_temp_and_syncs(logger):
    """Pas de personnes : pas d'insert batch, mais le sync SQL est appelé (cas pertinent : il agrège aussi `source_authorships` en SQL, donc peut produire des lignes)."""
    queries = _FakeQueries(persons_rows=[])
    conn = _FakeConn()

    populate(conn, queries, logger)

    assert queries.create_temp_called is True
    assert queries.batches == []
    assert queries.sync_called is True
    assert queries.drop_temp_called is True
    assert conn.committed is True


def test_single_person_single_batch(logger):
    """Quelques personnes : tout passe dans un seul `insert_raw_forms_batch` final."""
    queries = _FakeQueries(
        persons_rows=[
            {"id": 1, "last_name": "Dupont", "first_name": "Marie"},
            {"id": 2, "last_name": "Martin", "first_name": "Jean"},
        ]
    )
    conn = _FakeConn()

    populate(conn, queries, logger)

    # Un seul batch (sous le seuil BATCH_SIZE).
    assert len(queries.batches) == 1
    rows = queries.batches[0]
    assert rows, "Au moins une forme calculée par personne"
    # Chaque ligne porte le contrat attendu par sync_from_raw_forms.
    assert all(set(r.keys()) == {"raw_text", "person_id", "source"} for r in rows)
    assert all(r["source"] == "persons" for r in rows)
    assert {r["person_id"] for r in rows} == {1, 2}
    assert conn.committed is True


def test_strips_whitespace_in_names(logger):
    """Les noms / prénoms reçus de la DB sont strippés avant `compute_person_name_forms`."""
    queries = _FakeQueries(
        persons_rows=[{"id": 1, "last_name": "  Dupont  ", "first_name": "  Marie  "}]
    )
    conn = _FakeConn()

    populate(conn, queries, logger)

    rows = queries.batches[0]
    # Les formes générées s'appuient sur le strip ; aucune ne contient le whitespace de bord.
    for r in rows:
        assert not r["raw_text"].startswith(" ")
        assert not r["raw_text"].endswith(" ")


def test_handles_null_first_name(logger):
    """`first_name = None` est converti en chaîne vide avant strip — pas d'AttributeError."""
    queries = _FakeQueries(persons_rows=[{"id": 1, "last_name": "Sansprenom", "first_name": None}])
    conn = _FakeConn()

    populate(conn, queries, logger)

    assert queries.sync_called is True
    rows = queries.batches[0]
    assert all(r["person_id"] == 1 for r in rows)


def test_batches_flush_at_batch_size(monkeypatch, logger):
    """Au-delà de BATCH_SIZE lignes, le batch est flushé et un nouveau démarre.

    On baisse `BATCH_SIZE` à 3 pour ne pas avoir à générer 5000+ formes.
    """
    monkeypatch.setattr(populate_person_name_forms, "BATCH_SIZE", 3)

    # Chaque personne produit plusieurs formes ; quelques personnes suffisent à dépasser 3.
    queries = _FakeQueries(
        persons_rows=[
            {"id": i, "last_name": f"Nom{i}", "first_name": f"Prenom{i}"} for i in range(1, 5)
        ]
    )
    conn = _FakeConn()

    populate(conn, queries, logger)

    # Plusieurs flushes : au moins 2 batches.
    assert len(queries.batches) >= 2
    # Pas de batch vide.
    assert all(len(b) > 0 for b in queries.batches)
    # Premiers batches plafonnés à 3 (sauf possiblement le dernier qui peut être < 3).
    assert all(len(b) <= 3 for b in queries.batches[:-1])


def test_sync_return_values_logged(logger, caplog):
    """Le tuple (inserted, updated, deleted) renvoyé par `sync_from_raw_forms` est loggé."""
    queries = _FakeQueries(persons_rows=[])
    queries.sync_return = (42, 7, 3)
    conn = _FakeConn()

    with caplog.at_level(logging.INFO, logger=logger.name):
        populate(conn, queries, logger)

    final = caplog.records[-1].getMessage()
    assert "42" in final and "7" in final and "3" in final


def test_assert_BATCH_SIZE_default():
    """Le BATCH_SIZE par défaut est volontairement gros (commit en un seul lot SQL côté insertion).

    Pin la valeur courante pour éviter une régression silencieuse de perf.
    """
    assert BATCH_SIZE == 5000
