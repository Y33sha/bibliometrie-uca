"""Phase `extract_by_person` : moissonnage des sources par l'identifiant des personnes RH, vers le staging.

Un nœud par source de `PERSON_SEARCHED_SOURCES`, en parallèle, sur la plage d'années de l'extraction (ou `--year`). Le mode `daily` saute la phase. `--sources` restreint les sources.

Les identifiants de personne que chaque source accepte sont dans `domain/sources/person_search.py`.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from pipeline.graph import PERSON_SEARCHED_SOURCES
from pipeline.http.circuit_breaker import SourceCircuitBreaker
from pipeline.ingestion.common.extract import Extracteur
from pipeline.ingestion.common.harvest import ExtractionConfigError
from pipeline.node_runner import NodeRun, NodeStep, run_nodes
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.execution import open_tx
from pipeline.runtime.modes import MODES
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, etape
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unconfigured
from pipeline.runtime.parallel import RunParallel

if TYPE_CHECKING:
    from sqlalchemy import Connection

_SECTION = "Moissonnage par personne"

SearchOne = Callable[[str, argparse.Namespace, SourceCircuitBreaker | None], PhaseMetrics]


@dataclass(frozen=True)
class ExtractByPersonPhase:
    search_one: SearchOne
    run_parallel: RunParallel

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute en parallèle le nœud de chaque source retenue et assemble les métriques."""
        options = ctx.options
        if not MODES[options.mode].extract_by_person:
            etape(ctx.logger, _SECTION)
            ctx.logger.info("%sSautée en mode %s", DERNIERE_BRANCHE, options.mode)
            return PhaseMetrics()
        effective = set(PERSON_SEARCHED_SOURCES)
        if options.sources:
            effective &= options.sources

        def node(source: str) -> NodeRun:
            def run(ctx: PhaseContext, breaker: SourceCircuitBreaker | None) -> PhaseMetrics:
                args = argparse.Namespace(start_year=options.start_year, year=options.year)
                try:
                    return self.search_one(source, args, breaker)
                except ExtractionConfigError as exc:
                    metrics = PhaseMetrics()
                    signal_source_unconfigured(
                        metrics, source, str(exc), logger=ctx.logger, phase="extract_by_person"
                    )
                    return metrics

            return run

        def retenue(source: str) -> Callable[[PhaseContext], bool]:
            return lambda _ctx: source in effective

        by_node = run_nodes(
            "extract_by_person",
            {
                f"extract_by_person.{source}": NodeStep(
                    node(source),
                    section=_SECTION,
                    threshold=5,
                    when=retenue(source),
                )
                for source in PERSON_SEARCHED_SOURCES
            },
            ctx,
            parallel=self.run_parallel,
        )
        metrics = PhaseMetrics()
        for source_metrics in by_node.values():
            metrics.merge(source_metrics)
        return metrics


# ── Câblage ───────────────────────────────────────────────────


type ConstructeurExtracteur = Callable[[Connection, logging.Logger], Extracteur]


def build() -> Phase:
    """Moissonnage des sources par l'identifiant des personnes RH, vers le staging."""
    from pipeline.runtime.parallel import run_parallel

    registry = _extractors()

    def search_one(
        source: str, args: argparse.Namespace, breaker: SourceCircuitBreaker | None
    ) -> PhaseMetrics:
        source_log = setup_logger(source, str(PROJECT_ROOT / "logs"))
        with open_tx() as conn:
            return registry[source](conn, source_log).run(args, breaker=breaker)

    return ExtractByPersonPhase(search_one=search_one, run_parallel=run_parallel)


def _extractors() -> dict[str, ConstructeurExtracteur]:
    """Constructeur de l'extracteur par personne de chaque source. Chaque constructeur importe les modules de sa source au moment où il s'exécute."""
    from pipeline.ingestion.api_params import API_BASE_URLS

    def datacite(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.datacite.harvest import DataciteClient
        from pipeline.ingestion.datacite.person_search import DatacitePersonExtractor

        return DatacitePersonExtractor(conn, source_log, DataciteClient(API_BASE_URLS["datacite"]))

    def crossref(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.crossref.person_search import (
            CrossrefClient,
            CrossrefPersonExtractor,
        )

        return CrossrefPersonExtractor(conn, source_log, CrossrefClient(API_BASE_URLS["crossref"]))

    def openalex(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.openalex.harvest import OpenalexClient
        from pipeline.ingestion.openalex.person_search import OpenalexPersonExtractor

        return OpenalexPersonExtractor(conn, source_log, OpenalexClient(API_BASE_URLS["openalex"]))

    def hal(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.hal.harvest import HalClient
        from pipeline.ingestion.hal.person_search import HalPersonExtractor

        return HalPersonExtractor(conn, source_log, HalClient(API_BASE_URLS["hal"]))

    def scanr(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.scanr.harvest import ScanrClient
        from pipeline.ingestion.scanr.person_search import ScanrPersonExtractor
        from pipeline.runtime.config import get_scanr_credentials

        client = ScanrClient(API_BASE_URLS["scanr"], credentials=get_scanr_credentials())
        return ScanrPersonExtractor(conn, source_log, client)

    return {
        "datacite": datacite,
        "crossref": crossref,
        "openalex": openalex,
        "hal": hal,
        "scanr": scanr,
    }
