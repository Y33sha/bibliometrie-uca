"""Phase `extract_by_person` : interrogation des sources par l'identifiant des personnes RH, vers le staging.

Un nœud par source interrogée, en parallèle, sur la plage d'années de l'extraction (ou `--year`). Le mode quotidien saute la phase. Les sources retenues sont celles du mode et de `--sources`.

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
from pipeline.ingestion.common.extract import Extracteur
from pipeline.ingestion.common.harvest import ExtractionConfigError
from pipeline.ingestion.common.parallel import RunParallel
from pipeline.ingestion.http.circuit_breaker import SourceCircuitBreaker
from pipeline.node_runner import NodeRun, NodeStep, run_nodes
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.execution import open_tx
from pipeline.runtime.modes import MODES
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unconfigured

if TYPE_CHECKING:
    from sqlalchemy import Connection

SearchOne = Callable[[str, argparse.Namespace, SourceCircuitBreaker | None], PhaseMetrics]


@dataclass(frozen=True)
class ExtractByPersonPhase:
    search_one: SearchOne
    run_parallel: RunParallel

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Exécute en parallèle le nœud de chaque source retenue et assemble les métriques."""
        options = ctx.options
        policy = MODES[options.mode]
        effective = set(policy.extract_sources) if policy.year_selection == "full" else set()
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
                    section="Moissonnage par personne",
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
    """Interrogation des sources par l'identifiant des personnes RH, vers le staging."""
    from pipeline.ingestion.common.parallel import run_parallel

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
    from pipeline.ingestion.http.api_params import API_BASE_URLS

    def datacite(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.datacite.harvest import DataciteClient
        from pipeline.ingestion.datacite.person_search import DatacitePersonExtractor

        return DatacitePersonExtractor(conn, source_log, DataciteClient(API_BASE_URLS["datacite"]))

    return {"datacite": datacite}
