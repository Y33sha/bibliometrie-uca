"""Fixtures des tests des moissonneurs et des normaliseurs."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from pipeline.ingestion.common import harvest
from pipeline.ingestion.common.staging import UpsertOutcome

# Signaux `(inserted, changed)` d'`upsert_staging` pour chaque issue.
_SIGNAUX = {
    UpsertOutcome.NEW: (True, False),
    UpsertOutcome.UPDATED: (False, True),
    UpsertOutcome.UNCHANGED: (False, False),
}


@dataclass(frozen=True)
class Ecriture:
    """Un appel à `upsert_staging`."""

    source: str
    source_id: str
    doi: str | None
    authors_truncated: bool


@pytest.fixture
def configuration(monkeypatch):
    """Remplace la lecture de la configuration d'un moissonneur : identifiants du périmètre, années.

    Seules les fonctions que le module importe sont remplacées.
    """

    def _poser(
        module,
        *,
        api_ids: list[str] | None = None,
        annees: list[int] | None = None,
    ) -> None:
        lectures = {
            "get_extraction_api_ids": lambda conn, source: ["X"] if api_ids is None else api_ids,
            "get_years": lambda conn, start_year=None: [2024] if annees is None else annees,
        }
        for nom, lecture in lectures.items():
            if hasattr(module, nom):
                monkeypatch.setattr(module, nom, lecture)

    return _poser


@pytest.fixture
def ecritures(monkeypatch) -> list[Ecriture]:
    """Remplace l'écriture dans `staging` et renvoie la liste des écritures.

    L'issue de l'écriture est lue dans le champ `_route` du document (`UpsertOutcome.NEW` par défaut).
    """
    ecrits: list[Ecriture] = []

    def _upsert(conn, *, source, source_id, doi, raw_data, authors_truncated=False):
        ecrits.append(Ecriture(source, source_id, doi, authors_truncated))
        return _SIGNAUX[raw_data.get("_route", UpsertOutcome.NEW)]

    monkeypatch.setattr(harvest, "upsert_staging", _upsert)
    return ecrits


@pytest.fixture
def logger() -> logging.Logger:
    """Logger neutre pour les normaliseurs sous test (aucune sortie disque)."""
    return logging.getLogger("test_normalize")
