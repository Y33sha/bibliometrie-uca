"""Orchestrateur de la phase `extract` : sélection des sources par mode, skip des non configurées.

Les dépendances techniques (extraction d'une source, parallélisme, dernière date) sont injectées,
donc l'orchestrateur se teste sans I/O ni threads : `run_parallel` est remplacé par une exécution
synchrone déterministe.
"""

import logging
from datetime import date

from application.pipeline.extract import phase
from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.metrics import PhaseMetrics

_LOG = logging.getLogger("test")


def _sync_run_parallel(thunks):
    """Exécute les thunks en séquence (déterministe) — même contrat que le primitif parallèle."""
    return {label: thunk() for label, thunk in thunks.items()}


def test_parallel_skips_unconfigured_source():
    def extract_one(source, _args):
        if source == "openalex":
            raise ExtractionConfigError("aucune clé")
        return PhaseMetrics(new=3)

    metrics = phase.run(
        mode="full",
        sources={"openalex", "theses"},
        year=None,
        start_year=None,
        include_wos=False,
        extract_one=extract_one,
        run_parallel=_sync_run_parallel,
        get_last_extract_date=lambda _s: None,
        logger=_LOG,
    )

    assert {r["key"] for r in metrics.details["table"]["rows"]} == {"theses"}
    assert metrics.new == 3  # la source configurée est mergée
    assert [s["code"] for s in metrics.signals] == ["source_unconfigured"]


def test_since_last_extracts_hal_from_last_date():
    calls: list[tuple[str, str | None]] = []

    def extract_one(source, args):
        calls.append((source, args.since))
        return PhaseMetrics(new=5)

    metrics = phase.run(
        mode="daily",
        sources=None,
        year=None,
        start_year=None,
        include_wos=False,
        extract_one=extract_one,
        run_parallel=_sync_run_parallel,
        get_last_extract_date=lambda _s: date(2026, 1, 1),
        logger=_LOG,
    )

    assert calls == [
        ("hal", "2026-01-01")
    ]  # HAL seul, en incrémental depuis la dernière extraction
    assert metrics.details["table"]["rows"][0]["key"] == "hal"


def test_theses_ignores_year_range_bound():
    seen: dict[str, tuple[int | None, int | None]] = {}

    def extract_one(source, args):
        seen[source] = (args.start_year, args.year)
        return PhaseMetrics()

    phase.run(
        mode="full",
        sources={"hal", "theses"},
        year=None,
        start_year=2020,
        include_wos=False,
        extract_one=extract_one,
        run_parallel=_sync_run_parallel,
        get_last_extract_date=lambda _s: None,
        logger=_LOG,
    )

    assert seen["hal"] == (2020, None)  # borne large appliquée
    assert seen["theses"] == (None, None)  # theses ramène tout l'historique des PPN
