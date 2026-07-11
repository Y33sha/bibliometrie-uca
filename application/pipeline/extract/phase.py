"""Orchestrateur de la phase `extract` : moissonnage des sources vers le staging.

Workflow (sans I/O ni threads : ceux-ci sont injectés) :

- lit la policy du mode (`modes.py`) : sources autorisées et stratégie d'années ;
- mode `since_last` (quotidien) : HAL en incrémental depuis la dernière extraction HAL réussie ;
- sinon : toutes les sources retenues en parallèle, sur la plage `[start_year … courante]` (ou
  `--year`) ; `theses` ignore la borne large (tout l'historique des PPN, sauf `--year`) ;
- assemble les métriques par source et signale les sources non configurées.

Les trois dépendances techniques sont injectées par le composition-root :

- `extract_one(source, args)` : ouvre la connexion, câble l'adapter, exécute l'extraction sous
  circuit-breaker (les métriques rendues portent déjà l'éventuel signal `source_unavailable`), et
  lève `ExtractionConfigError` si la source n'est pas configurée ;
- `run_parallel` : le primitif de parallélisme (thread pool) ;
- `get_last_extract_date` : la date de la dernière extraction d'une source (branche incrémentale).
"""

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from application.pipeline.extract.base import ExtractionConfigError
from application.pipeline.metrics import PhaseMetrics
from application.pipeline.modes import MODES
from application.pipeline.signals import signal_source_unconfigured, timed_metrics
from application.ports.pipeline.parallel import RunParallel

ExtractOne = Callable[[str, argparse.Namespace], PhaseMetrics]
GetLastExtractDate = Callable[[str], date | None]

# Ordre de construction des tâches parallèles (les rows de la table suivent l'ordre d'achèvement).
_PARALLEL_SOURCES = ("openalex", "hal", "wos", "scanr", "theses")
# `theses` ne suit pas la borne d'années large : elle ramène tout l'historique des PPN (sauf --year).
_YEAR_BOUNDED_SOURCES = frozenset({"openalex", "hal", "wos", "scanr"})


def _extractor_args(
    *, start_year: int | None = None, year: int | None = None, since: str | None = None
) -> argparse.Namespace:
    """Construit le `args` consommé par `SourceExtractor.run` (dry_run, start_year, year, since). HAL et OpenAlex exploitent `since` (incrémental)."""
    return argparse.Namespace(dry_run=False, start_year=start_year, year=year, since=since)


def _source_summary(metrics: PhaseMetrics, duration_s: float) -> dict[str, float]:
    """Ligne « par source » de la table d'observabilité de la phase."""
    return {
        "found": metrics.total,
        "new": metrics.new,
        "updated": metrics.updated,
        "unchanged": metrics.unchanged,
        "errors": metrics.errors,
        "duration_s": round(duration_s, 1),
    }


@dataclass
class _SourceOutcome:
    """Issue d'une extraction de source : métriques + durée, ou motif de non-configuration."""

    metrics: PhaseMetrics | None
    duration: float
    unconfigured: str | None


def run(
    *,
    mode: str,
    sources: set[str] | None,
    year: int | None,
    start_year: int | None,
    include_wos: bool,
    extract_one: ExtractOne,
    run_parallel: RunParallel,
    get_last_extract_date: GetLastExtractDate,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Retient les sources effectives selon le mode, les extrait, et assemble les métriques."""
    policy = MODES[mode]
    allowed = set(policy.extract_sources) | ({"wos"} if include_wos else set())
    effective = (set(sources) if sources else allowed) & allowed
    metrics = PhaseMetrics()

    if policy.year_selection == "since_last":
        by_source = _run_since_last(effective, extract_one, get_last_extract_date, metrics, logger)
    else:
        by_source = _run_parallel_sources(
            effective, year, start_year, extract_one, run_parallel, metrics, logger
        )

    if by_source:
        metrics.details["table"] = {
            "rows": [{"key": source, **summary} for source, summary in by_source.items()]
        }
    return metrics


def _run_since_last(
    effective: set[str],
    extract_one: ExtractOne,
    get_last_extract_date: GetLastExtractDate,
    metrics: PhaseMetrics,
    logger: logging.Logger,
) -> dict[str, dict[str, float]]:
    """Mode quotidien : HAL depuis la dernière extraction HAL réussie (fallback -30 j)."""
    last = get_last_extract_date("hal")
    if last is not None:
        since = last.isoformat()
        logger.info("Mode quotidien : HAL depuis %s (dernière extraction HAL)", since)
    else:
        since = (date.today() - timedelta(days=30)).isoformat()
        logger.info("Mode quotidien : HAL depuis %s (fallback, aucune extraction HAL)", since)

    if "hal" not in effective:
        return {}
    try:
        hal_metrics, hal_duration = timed_metrics(
            lambda: extract_one("hal", _extractor_args(since=since))
        )
    except ExtractionConfigError as exc:
        signal_source_unconfigured(metrics, "hal", str(exc), logger=logger, phase="extract")
        return {}
    metrics.merge(hal_metrics)
    return {"hal": _source_summary(hal_metrics, hal_duration)}


def _run_parallel_sources(
    effective: set[str],
    year: int | None,
    start_year: int | None,
    extract_one: ExtractOne,
    run_parallel: RunParallel,
    metrics: PhaseMetrics,
    logger: logging.Logger,
) -> dict[str, dict[str, float]]:
    """Toutes les sources retenues en parallèle, chacune sur sa propre connexion et staging."""
    args_by_source = {
        source: _extractor_args(
            start_year=start_year if source in _YEAR_BOUNDED_SOURCES else None, year=year
        )
        for source in _PARALLEL_SOURCES
        if source in effective
    }
    if not args_by_source:
        return {}

    logger.info(
        "▶ extracteurs en parallèle (%d) : %s", len(args_by_source), ", ".join(args_by_source)
    )
    outcomes = run_parallel(
        {
            source: _extraction_thunk(extract_one, source, args)
            for source, args in args_by_source.items()
        }
    )

    by_source: dict[str, dict[str, float]] = {}
    for source, outcome in outcomes.items():
        if outcome.unconfigured is not None:
            signal_source_unconfigured(
                metrics, source, outcome.unconfigured, logger=logger, phase="extract"
            )
            continue
        assert outcome.metrics is not None
        metrics.merge(outcome.metrics)
        by_source[source] = _source_summary(outcome.metrics, outcome.duration)
    return by_source


def _extraction_thunk(
    extract_one: ExtractOne, source: str, args: argparse.Namespace
) -> Callable[[], _SourceOutcome]:
    """Enveloppe une extraction en thunk : chronométrée, la non-configuration rendue en valeur
    (jamais levée hors du thread) pour que le primitif de parallélisme n'ait pas à la connaître."""

    def thunk() -> _SourceOutcome:
        try:
            source_metrics, duration = timed_metrics(lambda: extract_one(source, args))
        except ExtractionConfigError as exc:
            return _SourceOutcome(None, 0.0, str(exc))
        return _SourceOutcome(source_metrics, duration, None)

    return thunk
