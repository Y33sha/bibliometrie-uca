"""Orchestrateur de la phase `extract` : moissonnage des sources vers le staging.

Workflow (sans I/O ni threads : ceux-ci sont injectés) :

- s'arrête en échec si le périmètre d'extraction ne contient aucune structure ;
- lit la policy du mode (`modes.py`) : sources autorisées et stratégie d'années ;
- mode `since_last` (quotidien) : HAL en incrémental depuis la dernière extraction quotidienne réussie ;
- sinon : un nœud par source retenue, en parallèle, sur la plage `[start_year … courante]` (ou `--year`) ; `theses` ignore la borne large (tout l'historique des PPN, sauf `--year`) ;
- assemble les métriques par source et signale les sources non configurées.

Les dépendances techniques sont injectées par le composition-root :

- `count_extraction_structures(ctx)` : le nombre de structures du périmètre d'extraction ;
- `extract_one(ctx, source, args, breaker)` : ouvre la connexion, câble l'extracteur et l'exécute sous le circuit-breaker de la source ; lève `ExtractionConfigError` si le périmètre d'interrogation de la source manque ;
- `run_parallel` : le primitif de parallélisme (thread pool) ;
- `get_last_daily_extract_date` : la date de la dernière extraction quotidienne réussie (branche incrémentale).
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Protocol

from domain.dates import date_to_french, today
from domain.sources.registry import HARVESTED_SOURCES
from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from pipeline.http.circuit_breaker import SourceCircuitBreaker
from pipeline.ingestion.common.harvest import ExtractionConfigError
from pipeline.node_runner import NodeRun, NodeStep, run_nodes
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import BRANCHE
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unconfigured, skipped
from pipeline.runtime.parallel import RunParallel
from pipeline.transformation.structures.perimeter import EmptyExtractionPerimeterError

if TYPE_CHECKING:
    from sqlalchemy import Connection


ExtractOne = Callable[
    [PhaseContext, str, argparse.Namespace, SourceCircuitBreaker | None], PhaseMetrics
]
GetLastDailyExtractDate = Callable[[], date | None]

# `theses` ne suit pas la borne d'années large : elle ramène tout l'historique des PPN (sauf --year).
_YEAR_BOUNDED_SOURCES = frozenset({"openalex", "hal", "wos", "scanr", "datacite"})


def _extractor_args(
    *, start_year: int | None = None, year: int | None = None, since: str | None = None
) -> argparse.Namespace:
    """Construit le `args` consommé par `SourceExtractor.run` (start_year, year, since). HAL et OpenAlex exploitent `since` (incrémental)."""
    return argparse.Namespace(start_year=start_year, year=year, since=since)


def _source_summary(metrics: PhaseMetrics) -> dict[str, float | None]:
    """Ligne « par source » de la table d'observabilité de la phase."""
    return {
        "found": metrics.total,
        "new": metrics.new,
        "updated": metrics.updated,
        "unchanged": metrics.unchanged,
        "errors": metrics.errors,
        "duration_s": metrics.duration_s,
    }


@dataclass(frozen=True)
class ExtractPhase:
    count_extraction_structures: Callable[[PhaseContext], int]
    extract_one: ExtractOne
    run_parallel: RunParallel
    get_last_daily_extract_date: GetLastDailyExtractDate

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Retient les sources effectives selon le mode, exécute leurs nœuds en parallèle, et assemble les métriques."""
        options = ctx.options
        if self.count_extraction_structures(ctx) == 0:
            raise EmptyExtractionPerimeterError()
        policy = options.policy
        effective = set(policy.extract_sources) | ({"wos"} if options.include_wos else set())
        effective &= options.sources
        depuis = self._since_last_daily() if policy.year_selection == "since_last" else None
        since = depuis[0].isoformat() if depuis else None
        if depuis is not None:
            # Le mode quotidien moissonne HAL seul.
            effective &= {"hal"}

        def node(source: str) -> NodeRun:
            def run(ctx: PhaseContext, breaker: SourceCircuitBreaker | None) -> PhaseMetrics:
                if depuis is not None and source == "hal":
                    ctx.logger.info(
                        "%sMode incrémental : notices HAL modifiées depuis le %s (%s)",
                        BRANCHE,
                        date_to_french(depuis[0]),
                        depuis[1],
                    )
                args = _extractor_args(
                    start_year=options.start_year if source in _YEAR_BOUNDED_SOURCES else None,
                    year=options.year,
                    since=since,
                )
                try:
                    return self.extract_one(ctx, source, args, breaker)
                except ExtractionConfigError as exc:
                    metrics = PhaseMetrics()
                    signal_source_unconfigured(
                        metrics, source, str(exc), logger=ctx.logger, phase="extract"
                    )
                    return metrics

            return run

        def retenue(source: str) -> Callable[[PhaseContext], bool]:
            return lambda _ctx: source in effective

        by_node = run_nodes(
            "extract",
            {
                f"extract.{source}": NodeStep(
                    node(source),
                    section="Moissonnage par affiliation",
                    threshold=5,
                    when=retenue(source),
                )
                for source in HARVESTED_SOURCES
            },
            ctx,
            parallel=self.run_parallel,
        )

        metrics = PhaseMetrics()
        by_source: dict[str, dict[str, float | None]] = {}
        for source in HARVESTED_SOURCES:
            source_metrics = by_node[f"extract.{source}"]
            metrics.merge(source_metrics)
            if source in effective and not skipped(source_metrics):
                by_source[source] = _source_summary(source_metrics)
        if by_source:
            metrics.details["table"] = {
                "rows": [{"key": source, **summary} for source, summary in by_source.items()]
            }
        return metrics

    def _since_last_daily(self) -> tuple[date, str]:
        """Mode quotidien : date depuis laquelle HAL est moissonné, avec son origine — la dernière extraction quotidienne réussie, ou les 30 derniers jours."""
        last = self.get_last_daily_extract_date()
        if last is not None:
            return last, "dernière extraction quotidienne réussie"
        return today() - timedelta(
            days=30
        ), "aucune extraction quotidienne réussie, repli sur 30 jours"


# ── Câblage ───────────────────────────────────────────────────


class Extracteur(Protocol):
    """Point d'entrée commun des extracteurs, seul que l'orchestrateur appelle.

    Chaque source a son type de configuration et son client ; ce protocole les laisse aux extracteurs.
    """

    def run(
        self,
        args: argparse.Namespace,
        *,
        breaker: SourceCircuitBreaker | None = None,
    ) -> PhaseMetrics: ...


# Un extracteur se construit sur la connexion de sa phase et le journal scopé à sa source.
type ConstructeurExtracteur = Callable[[Connection, logging.Logger], Extracteur]


def build() -> Phase:
    """Extraction des sources vers staging.

    `pipeline/runtime/modes.py` définit la policy du mode : sources retenues et stratégie d'années. Séquence, parallélisme et métriques dans `pipeline/ingestion/common/extract.py` ; ici, le câblage : registre des extracteurs, primitif de parallélisme, lecture de la date de dernière extraction.
    """
    from infrastructure.observability.phase_executions import get_last_daily_extract_date
    from pipeline.runtime.parallel import run_parallel

    registry = _extractors()

    def extract_one(
        ctx: PhaseContext,
        source: str,
        args: argparse.Namespace,
        breaker: SourceCircuitBreaker | None,
    ) -> PhaseMetrics:
        return _run_extract(ctx, source, registry[source], args, breaker)

    return ExtractPhase(
        count_extraction_structures=_extraction_structure_count,
        extract_one=extract_one,
        run_parallel=run_parallel,
        get_last_daily_extract_date=get_last_daily_extract_date,
    )


def _extraction_structure_count(ctx: PhaseContext) -> int:
    """Nombre de structures du périmètre d'extraction, lu dans `perimeter_structures`."""
    from pipeline.transformation.structures.perimeter import PerimeterQueries

    with ctx.open_tx() as conn:
        return PerimeterQueries().count_extraction_structures(conn)


def _extractors() -> dict[str, ConstructeurExtracteur]:
    """Constructeur de l'extracteur de chaque source : `(conn, source_log)` → extracteur câblé.

    `wos` et `scanr` lisent leurs identifiants d'API en configuration.

    Chaque constructeur importe les modules de sa source au moment où il s'exécute. Une source écartée du run ne charge donc pas son code, et un défaut qui l'atteint laisse les autres tourner."""
    from pipeline.ingestion.api_params import API_BASE_URLS

    def hal(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.hal.harvest import HalClient, HalExtractor

        return HalExtractor(conn, source_log, HalClient(API_BASE_URLS["hal"]))

    def openalex(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.openalex.harvest import OpenalexClient, OpenalexExtractor

        return OpenalexExtractor(conn, source_log, OpenalexClient(API_BASE_URLS["openalex"]))

    def wos(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.wos.harvest import WosClient, WosExtractor
        from pipeline.runtime.config import get_wos_api_key

        client = WosClient(API_BASE_URLS["wos"], api_key=get_wos_api_key())
        return WosExtractor(conn, source_log, client)

    def scanr(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.scanr.harvest import ScanrClient, ScanrExtractor
        from pipeline.runtime.config import get_scanr_credentials

        client = ScanrClient(API_BASE_URLS["scanr"], credentials=get_scanr_credentials())
        return ScanrExtractor(conn, source_log, client)

    def theses(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.theses.harvest import ThesesClient, ThesesExtractor

        return ThesesExtractor(conn, source_log, ThesesClient(API_BASE_URLS["theses"]))

    def datacite(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.ingestion.datacite.harvest import DataciteClient, DataciteExtractor

        return DataciteExtractor(conn, source_log, DataciteClient(API_BASE_URLS["datacite"]))

    return {
        "hal": hal,
        "openalex": openalex,
        "wos": wos,
        "scanr": scanr,
        "theses": theses,
        "datacite": datacite,
    }


def _run_extract(
    ctx: PhaseContext,
    source: str,
    make_extractor: ConstructeurExtracteur,
    args: argparse.Namespace,
    breaker: SourceCircuitBreaker | None,
) -> PhaseMetrics:
    """Déroulé commun d'une extraction : ouverture de la connexion, exécution sous le circuit-breaker de la source, fermeture. `make_extractor` contient le câblage propre à la source."""
    source_log = setup_logger(source, str(PROJECT_ROOT / "logs"))
    with ctx.open_tx() as conn:
        return make_extractor(conn, source_log).run(args, breaker=breaker)
