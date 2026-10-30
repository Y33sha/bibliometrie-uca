"""Tests unitaires de `populate_person_name_forms.populate`.

Les fonctions SQL du module sont simulées, sans base de données.

`populate` calcule les formes du nom de chaque personne (`compute_person_name_forms`), les insère par lots dans une table temporaire, puis lance la synchronisation SQL.
"""

from __future__ import annotations

import logging

import pytest

from pipeline.transformation.persons import populate_person_name_forms
from pipeline.transformation.persons.populate_person_name_forms import (
    BATCH_SIZE,
    PersonNameRow,
    RawFormBatchItem,
    SyncCounts,
    populate,
)


class _FakeQueries:
    def __init__(self) -> None:
        self.persons_rows: list[PersonNameRow] = []
        self.create_temp_called = False
        self.drop_temp_called = False
        self.batches: list[list[RawFormBatchItem]] = []
        self.sync_return = SyncCounts(0, 0, 0)
        self.sync_called = False

    def fetch_persons_names(self, conn: object) -> list[PersonNameRow]:
        return self.persons_rows

    def create_temp_raw_forms_table(self, conn: object) -> None:
        self.create_temp_called = True

    def insert_raw_forms_batch(self, conn: object, rows: list[RawFormBatchItem]) -> None:
        # Copie du lot, pour garder son contenu au moment de l'appel.
        self.batches.append(list(rows))

    def drop_temp_raw_forms_table(self, conn: object) -> None:
        self.drop_temp_called = True

    def sync_from_raw_forms(self, conn: object) -> SyncCounts:
        self.sync_called = True
        return self.sync_return


class _FakeConn:
    """Connexion factice : `populate` la passe aux fonctions SQL remplacées, sans committer."""


@pytest.fixture
def queries(monkeypatch: pytest.MonkeyPatch) -> _FakeQueries:
    fake = _FakeQueries()
    for name in (
        "fetch_persons_names",
        "create_temp_raw_forms_table",
        "insert_raw_forms_batch",
        "drop_temp_raw_forms_table",
        "sync_from_raw_forms",
    ):
        monkeypatch.setattr(populate_person_name_forms, name, getattr(fake, name))
    return fake


def test_rend_le_bilan_de_la_synchronisation(queries):
    queries.sync_return = SyncCounts(inserted=3, updated=1, deleted=2)

    assert populate(_FakeConn()) == SyncCounts(3, 1, 2)


def test_empty_persons_still_creates_temp_and_syncs(queries):
    """Sans personne, aucun lot n'est inséré et la synchronisation SQL a lieu : elle ajoute aussi les noms des contributions sources des contributions."""
    populate(_FakeConn())

    assert queries.create_temp_called is True
    assert queries.batches == []
    assert queries.sync_called is True
    assert queries.drop_temp_called is True


def test_single_person_single_batch(queries):
    """Quelques personnes : toutes leurs formes passent dans un seul lot."""
    queries.persons_rows = [
        PersonNameRow(id=1, last_name="Dupont", first_name="Marie"),
        PersonNameRow(id=2, last_name="Martin", first_name="Jean"),
    ]

    populate(_FakeConn())

    # Un seul lot, sous le seuil BATCH_SIZE.
    assert len(queries.batches) == 1
    rows = queries.batches[0]
    assert rows, "Au moins une forme calculée par personne"
    # Chaque ligne a les clés lues par sync_from_raw_forms.
    assert all(set(r.keys()) == {"name_form", "person_id", "source"} for r in rows)
    assert all(r["source"] == "persons" for r in rows)
    assert {r["person_id"] for r in rows} == {1, 2}


def test_strips_whitespace_in_names(queries):
    """Les espaces de bord des noms et prénoms lus en base sont retirés avant `compute_person_name_forms`."""
    queries.persons_rows = [PersonNameRow(id=1, last_name="  Dupont  ", first_name="  Marie  ")]

    populate(_FakeConn())

    rows = queries.batches[0]
    for r in rows:
        assert not r["name_form"].startswith(" ")
        assert not r["name_form"].endswith(" ")


def test_handles_null_first_name(queries):
    """Un prénom absent est traité comme une chaîne vide."""
    queries.persons_rows = [PersonNameRow(id=1, last_name="Sansprenom", first_name=None)]

    populate(_FakeConn())

    assert queries.sync_called is True
    rows = queries.batches[0]
    assert all(r["person_id"] == 1 for r in rows)


def test_batches_flush_at_batch_size(queries, monkeypatch):
    """Un lot qui atteint `BATCH_SIZE` lignes est inséré, et le lot suivant commence."""
    monkeypatch.setattr(populate_person_name_forms, "BATCH_SIZE", 3)

    # Chaque personne produit plusieurs formes ; quelques personnes suffisent à dépasser 3.
    queries.persons_rows = [
        PersonNameRow(id=i, last_name=f"Nom{i}", first_name=f"Prenom{i}") for i in range(1, 5)
    ]

    populate(_FakeConn())

    assert len(queries.batches) >= 2
    assert all(len(b) > 0 for b in queries.batches)
    # Chaque lot sauf le dernier compte au plus trois formes.
    assert all(len(b) <= 3 for b in queries.batches[:-1])


def test_la_table_temporaire_ne_survit_pas_a_la_synchronisation(queries, caplog):
    """Les formes calculées transitent par une table temporaire, consommée par la synchronisation."""
    queries.sync_return = SyncCounts(42, 7, 3)

    with caplog.at_level(logging.INFO):
        populate(_FakeConn())

    assert queries.sync_called is True
    assert queries.drop_temp_called is True
    # La sous-étape se signale par sa ligne d'attente, sans détailler ses compteurs.
    assert caplog.records == []


def test_assert_BATCH_SIZE_default():
    """La taille de lot par défaut est de 5000 formes."""
    assert BATCH_SIZE == 5000
