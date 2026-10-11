"""Nouvelle lecture des documents anciens (`pipeline.sources.fetch_stale.refresh`).

Les trois issues d'une lecture par identifiant natif sont routées correctement :
- document trouvé (empreinte changée / inchangée) → écriture dans `staging` (updated / unchanged) ;
- absence confirmée (`NOT_FOUND`) → `disappeared_at` ;
- source indisponible (`UNAVAILABLE`) → rien, compté en `errors`, ni écrit ni marqué disparu.
"""

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from application.ports.pipeline.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.sources import fetch_stale
from pipeline.sources.fetch_stale import FetchedRecord, StaleRefetch, refresh


class _Lecture(StaleRefetch):
    """Lecture simulée : l'issue de chaque identifiant est posée par `outcomes`."""

    source_key = "openalex"
    max_concurrent = 2

    def __init__(self, outcomes: dict) -> None:
        self.outcomes = outcomes

    async def fetch_by_native_id(self, client, source_id):
        return self.outcomes[source_id]


@dataclass
class _Base:
    """Base simulée : la sélection rend les identifiants de la lecture, les écritures sont retenues."""

    ecrits: list[str] = field(default_factory=list)
    disparus: list[str] = field(default_factory=list)


@pytest.fixture
def lancer(monkeypatch):
    """Lance `refresh` sur une lecture simulée ; rend les métriques et la base simulée."""

    def _lancer(outcomes: dict):
        base = _Base()

        def _upsert(conn, *, source, source_id, doi, raw_data):
            base.ecrits.append(source_id)
            return False, bool(raw_data["changed"])

        monkeypatch.setattr(
            fetch_stale,
            "get_stale_source_ids",
            lambda conn, source, years, *, after_days: list(outcomes),
        )
        monkeypatch.setattr(fetch_stale, "upsert_staging", _upsert)
        monkeypatch.setattr(
            fetch_stale,
            "set_disappeared",
            lambda conn, source, source_id: base.disparus.append(source_id),
        )
        metrics = asyncio.run(
            refresh(MagicMock(), _Lecture(outcomes), logging.getLogger("test"), after_days=90)
        )
        return metrics, base

    return _lancer


_QUATRE_ISSUES = {
    "A": FetchedRecord(doi="10.1/a", raw_data={"changed": True}),
    "B": FetchedRecord(doi="10.1/b", raw_data={"changed": False}),
    "C": NOT_FOUND,
    "D": UNAVAILABLE,
}


def test_routes_each_outcome(lancer):
    metrics, base = lancer(_QUATRE_ISSUES)

    assert set(base.ecrits) == {"A", "B"}
    assert base.disparus == ["C"]
    assert (metrics.updated, metrics.unchanged, metrics.errors, metrics.total) == (1, 1, 1, 4)
    assert metrics.extras.get("disappeared") == 1


def test_transient_failure_is_noop(lancer):
    # Un échec transitoire ne marque jamais le document disparu : l'absence n'est pas prouvée.
    metrics, base = lancer({"X": UNAVAILABLE})
    assert (base.ecrits, base.disparus, metrics.errors) == ([], [], 1)


def test_empty_is_noop(lancer):
    metrics, base = lancer({})
    assert metrics.total == 0
    assert base.ecrits == []


def test_progress_counter_counts_documents_found_at_the_source(monkeypatch, lancer):
    """Le compteur de la barre porte les documents retrouvés à la source ; une disparition ou une erreur fait seulement avancer la barre."""

    class _Spy:
        avances = 0
        retenus = 0

        def avance(self, n=1):
            self.avances += n

        def retient(self, n=1):
            self.retenus += n

    spy = _Spy()
    options = {}

    @contextmanager
    def _progression(total, libelle, logger, **kwargs):
        options.update(kwargs)
        yield spy

    monkeypatch.setattr(fetch_stale, "progression", _progression)
    lancer(_QUATRE_ISSUES)

    assert options.get("compte_retenus") is True
    assert (spy.avances, spy.retenus) == (4, 2)
