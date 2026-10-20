"""Phase `extract_by_person` : moissonnage des sources par l'identifiant des personnes RH, vers le staging.

Une tâche par source de `PERSON_SEARCHED_SOURCES`, en parallèle, sur la plage d'années de l'extraction (ou `--year`). Le mode `daily` saute la phase. `--sources` restreint les sources.

Les identifiants de personne que chaque source accepte sont dans `domain/sources/person_search.py`.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.sources.registry import source_label
from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from pipeline.graph import PERSON_SEARCHED_SOURCES
from pipeline.http.circuit_breaker import SourceCircuitBreaker
from pipeline.ingestion.common.harvest import (
    ExtractionConfigError,
    Extractor,
    ExtractorFactory,
)
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unconfigured
from pipeline.runtime.parallel import RunParallel
from pipeline.task_runner import TaskRun, TaskStep, run_tasks

if TYPE_CHECKING:
    from sqlalchemy import Connection


SearchOne = Callable[
    [PhaseContext, str, argparse.Namespace, SourceCircuitBreaker | None], PhaseMetrics
]


@dataclass(frozen=True)
class ExtractByPersonPhase:
    search_one: SearchOne
    run_parallel: RunParallel

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute en parallèle la tâche de chaque source retenue et assemble les métriques."""
        options = ctx.options
        if not options.policy.extract_by_person:
            ctx.logger.info("%sSautée en mode %s", DERNIERE_BRANCHE, options.mode)
            return PhaseMetrics()
        effective = set(PERSON_SEARCHED_SOURCES) & options.sources

        def task(source: str) -> TaskRun:
            def run(ctx: PhaseContext, breaker: SourceCircuitBreaker | None) -> PhaseMetrics:
                args = argparse.Namespace(start_year=options.start_year, year=options.year)
                try:
                    return self.search_one(ctx, source, args, breaker)
                except ExtractionConfigError as exc:
                    metrics = PhaseMetrics()
                    signal_source_unconfigured(
                        metrics, source, str(exc), logger=ctx.logger, phase="extract_by_person"
                    )
                    return metrics

            return run

        def retenue(source: str) -> Callable[[PhaseContext], bool]:
            return lambda _ctx: source in effective

        by_task = run_tasks(
            "extract_by_person",
            {
                f"extract_by_person.{source}": TaskStep(
                    task(source),
                    label=source_label(source),
                    progress_bar=True,
                    threshold=5,
                    when=retenue(source),
                )
                for source in PERSON_SEARCHED_SOURCES
            },
            ctx,
            parallel=self.run_parallel,
        )
        metrics = PhaseMetrics()
        for source_metrics in by_task.values():
            metrics.merge(source_metrics)
        return metrics


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    from pipeline.runtime.parallel import run_parallel

    registry = _extractors()

    def search_one(
        ctx: PhaseContext,
        source: str,
        args: argparse.Namespace,
        breaker: SourceCircuitBreaker | None,
    ) -> PhaseMetrics:
        source_log = setup_logger(source, str(PROJECT_ROOT / "logs"))
        with ctx.open_tx() as conn:
            return registry[source](conn, source_log).run(args, breaker=breaker)

    return ExtractByPersonPhase(search_one=search_one, run_parallel=run_parallel)


def _extractors() -> dict[str, ExtractorFactory]:
    """Constructeur de l'extracteur par personne de chaque source. Chaque constructeur importe les modules de sa source au moment où il s'exécute."""
    from pipeline.ingestion.api_params import API_BASE_URLS

    def datacite(conn: Connection, source_log: logging.Logger) -> Extractor:
        from pipeline.ingestion.datacite.api import DataciteClient
        from pipeline.ingestion.datacite.person_search import DatacitePersonExtractor

        return DatacitePersonExtractor(conn, source_log, DataciteClient(API_BASE_URLS["datacite"]))

    def crossref(conn: Connection, source_log: logging.Logger) -> Extractor:
        from pipeline.ingestion.crossref.api import CrossrefClient
        from pipeline.ingestion.crossref.person_search import CrossrefPersonExtractor

        return CrossrefPersonExtractor(conn, source_log, CrossrefClient(API_BASE_URLS["crossref"]))

    def openalex(conn: Connection, source_log: logging.Logger) -> Extractor:
        from pipeline.ingestion.openalex.api import OpenalexClient
        from pipeline.ingestion.openalex.person_search import OpenalexPersonExtractor

        return OpenalexPersonExtractor(conn, source_log, OpenalexClient(API_BASE_URLS["openalex"]))

    def hal(conn: Connection, source_log: logging.Logger) -> Extractor:
        from pipeline.ingestion.hal.api import HalClient
        from pipeline.ingestion.hal.person_search import HalPersonExtractor

        return HalPersonExtractor(conn, source_log, HalClient(API_BASE_URLS["hal"]))

    def scanr(conn: Connection, source_log: logging.Logger) -> Extractor:
        from pipeline.ingestion.credentials import get_scanr_credentials
        from pipeline.ingestion.scanr.harvest import ScanrClient
        from pipeline.ingestion.scanr.person_search import ScanrPersonExtractor

        client = ScanrClient(API_BASE_URLS["scanr"], credentials=get_scanr_credentials())
        return ScanrPersonExtractor(conn, source_log, client)

    return {
        "datacite": datacite,
        "crossref": crossref,
        "openalex": openalex,
        "hal": hal,
        "scanr": scanr,
    }
