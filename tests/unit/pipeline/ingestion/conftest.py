"""Fixtures des tests des moissonneurs et des normaliseurs."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from domain.persons.identifiers import PersonIdentifierType
from domain.sources.staging import StagingEntryMode
from pipeline.ingestion.common import harvester, person_search
from pipeline.ingestion.common.staging import StagingStore, UpsertOutcome

# Signaux `(inserted, changed)` de `StagingStore.upsert` pour chaque issue.
_SIGNAUX = {
    UpsertOutcome.NEW: (True, False),
    UpsertOutcome.UPDATED: (False, True),
    UpsertOutcome.UNCHANGED: (False, False),
}


@dataclass(frozen=True)
class Ecriture:
    """Un appel à `StagingStore.upsert`."""

    source: str
    source_id: str
    doi: str | None
    authors_truncated: bool
    entry_mode: StagingEntryMode = StagingEntryMode.BULK


@pytest.fixture
def configuration(monkeypatch):
    """Pose la configuration lue par un moissonneur : identifiants du périmètre, années.

    Les identifiants sont posés dans le module du moissonneur s'il les lit, les années dans la classe commune des moissonneurs.
    """

    def _poser(
        module,
        *,
        api_ids: list[str] | None = None,
        annees: list[int] | None = None,
    ) -> None:
        if hasattr(module, "get_extraction_api_ids"):
            monkeypatch.setattr(
                module,
                "get_extraction_api_ids",
                lambda conn, source: ["X"] if api_ids is None else api_ids,
            )
        monkeypatch.setattr(
            harvester,
            "window_years",
            lambda conn, *, start_year, year: (
                [year] if year else [2024] if annees is None else annees
            ),
        )

    return _poser


@pytest.fixture
def ecritures(monkeypatch) -> list[Ecriture]:
    """Simule l'écriture dans `staging` et renvoie la liste des écritures.

    L'issue de l'écriture est lue dans le champ `_route` du document (`UpsertOutcome.NEW` par défaut).
    """
    ecrits: list[Ecriture] = []

    def _upsert(
        _store,
        *,
        source,
        source_id,
        doi,
        raw_data,
        authors_truncated=False,
        entry_mode=StagingEntryMode.BULK,
    ):
        ecrits.append(Ecriture(source, source_id, doi, authors_truncated, entry_mode))
        return _SIGNAUX[raw_data.get("_route", UpsertOutcome.NEW)]

    monkeypatch.setattr(StagingStore, "upsert", _upsert)
    return ecrits


@pytest.fixture
def identifiants_rh(monkeypatch, configuration):
    """Pose les personnes interrogées par le moissonnage par personne, sur les années 2024 et 2025.

    Une chaîne désigne une personne à un seul ORCID ; un dictionnaire, les identifiants d'une personne par type.
    """
    configuration(person_search, annees=[2024, 2025])

    def _poser(personnes: list) -> None:
        identifiants = [
            p if isinstance(p, dict) else {PersonIdentifierType.ORCID: [p]} for p in personnes
        ]
        monkeypatch.setattr(person_search, "searched_persons", lambda conn, id_types: identifiants)

    return _poser


@pytest.fixture
def logger() -> logging.Logger:
    """Renvoie un logger neutre, sans sortie disque, pour les normaliseurs sous test."""
    return logging.getLogger("test_normalize")
