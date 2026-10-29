"""Relecture des documents anciens (`pipeline.ingestion.common.stale_refetch.refresh`).

Chaque issue d'une lecture par identifiant natif a son traitement :
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

from pipeline.http.lookup import NOT_FOUND, UNAVAILABLE
from pipeline.ingestion.common import lookup, stale_refetch
from pipeline.ingestion.common.staging import StagingStore
from pipeline.ingestion.common.stale_refetch import StaleRefetch, refresh


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
    """Base simulée : la sélection renvoie les identifiants de la lecture, les écritures sont retenues."""

    ecrits: list[str] = field(default_factory=list)
    disparus: list[str] = field(default_factory=list)


@pytest.fixture
def lancer(monkeypatch):
    """Lance `refresh` sur une lecture simulée ; renvoie les métriques et la base simulée."""

    def _lancer(outcomes: dict):
        base = _Base()

        def _upsert(_store, *, source, source_id, doi, raw_data, authors_truncated, entry_mode):
            base.ecrits.append(source_id)
            return False, bool(raw_data["changed"])

        monkeypatch.setattr(
            stale_refetch,
            "get_stale_source_ids",
            lambda conn, source, years, *, after_days: list(outcomes),
        )
        monkeypatch.setattr(StagingStore, "upsert", _upsert)
        monkeypatch.setattr(
            stale_refetch,
            "set_disappeared",
            lambda conn, source, source_id: base.disparus.append(source_id),
        )
        metrics = asyncio.run(
            refresh(MagicMock(), _Lecture(outcomes), logging.getLogger("test"), after_days=90)
        )
        return metrics, base

    return _lancer


_QUATRE_ISSUES = {
    "A": {"id": "https://openalex.org/A", "changed": True},
    "B": {"id": "https://openalex.org/B", "changed": False},
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
    # Un échec transitoire laisse l'absence non établie : le document reste présent.
    metrics, base = lancer({"X": UNAVAILABLE})
    assert (base.ecrits, base.disparus, metrics.errors) == ([], [], 1)


def test_empty_is_noop(lancer):
    metrics, base = lancer({})
    assert metrics.total == 0
    assert base.ecrits == []


def test_progress_counter_counts_documents_found_at_the_source(monkeypatch, lancer):
    """Le compteur de la barre compte les documents retrouvés à la source ; une disparition ou une erreur fait seulement avancer la barre."""

    class _Spy:
        avances = 0
        kept = 0

        def advance(self, n=1):
            self.avances += n

        def keep(self, n=1):
            self.kept += n

    spy = _Spy()
    options = {}

    @contextmanager
    def _track_progress(total, label, logger, **kwargs):
        options.update(kwargs)
        yield spy

    monkeypatch.setattr(lookup, "track_progress", _track_progress)
    lancer(_QUATRE_ISSUES)

    assert options.get("count_kept") is True
    assert (spy.avances, spy.kept) == (4, 2)
