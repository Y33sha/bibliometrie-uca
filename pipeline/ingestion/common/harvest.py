"""Orchestrateur de la phase `harvest` : moissonnage des sources vers le staging.

Workflow (sans I/O ni threads : ceux-ci sont injectés) :

- s'arrête en échec si le périmètre d'extraction ne contient aucune structure ;
- lit la policy du mode (`modes.py`) : sources autorisées et stratégie d'années ;
- mode `since_last` (quotidien) : HAL en incrémental depuis le dernier moissonnage quotidien réussi ;
- sinon : une tâche par source retenue, en parallèle, sur la plage `[start_year … courante]` (ou `--year`) ; `theses` ignore la borne large (tout l'historique des PPN, sauf `--year`) ;
- assemble les métriques par source et signale les sources non configurées.

Les dépendances techniques sont injectées par le composition-root :

- `count_extraction_structures(ctx)` : le nombre de structures du périmètre d'extraction ;
- `harvest_one(ctx, source, window)` : ouvre la connexion, câble le moissonneur et l'exécute ; lève `HarvestConfigError` si le périmètre d'interrogation de la source manque ;
- `run_parallel` : le primitif de parallélisme (thread pool) ;
- `get_last_daily_harvest_date` : la date du dernier moissonnage quotidien réussi (branche incrémentale).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from domain.dates import date_to_french, today
from domain.sources.registry import HARVESTED_SOURCES, source_label
from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from infrastructure.observability.phase_executions import get_last_daily_harvest_date
from infrastructure.read_models.perimeters import get_extraction_structure_ids
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.harvester import (
    HarvestConfigError,
    Harvester,
    HarvesterFactory,
    HarvestWindow,
)
from pipeline.ingestion.credentials import get_scanr_credentials, get_wos_api_key
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.signals import signal_source_unconfigured, skipped
from pipeline.runtime.parallel import RunParallel, run_parallel
from pipeline.task_runner import TaskRun, TaskStep, run_tasks
from pipeline.transformation.structures.perimeter import EmptyExtractionPerimeterError

if TYPE_CHECKING:
    from sqlalchemy import Connection


HarvestOne = Callable[[PhaseContext, str, HarvestWindow], PhaseMetrics]
GetLastDailyHarvestDate = Callable[[], date | None]

# `theses` ne suit pas la borne d'années large : elle ramène tout l'historique des PPN (sauf --year).
_YEAR_BOUNDED_SOURCES = frozenset({"openalex", "hal", "wos", "scanr", "datacite"})


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
class HarvestPhase:
    count_extraction_structures: Callable[[PhaseContext], int]
    harvest_one: HarvestOne
    run_parallel: RunParallel
    get_last_daily_harvest_date: GetLastDailyHarvestDate

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Retient les sources effectives selon le mode, exécute leurs tâches en parallèle, et assemble les métriques."""
        options = ctx.options
        if self.count_extraction_structures(ctx) == 0:
            raise EmptyExtractionPerimeterError()
        policy = options.policy
        effective = set(policy.harvest_sources) | ({"wos"} if options.include_wos else set())
        effective &= options.sources
        last_daily = self._since_last_daily() if policy.year_selection == "since_last" else None
        since = last_daily[0].isoformat() if last_daily else None
        if last_daily is not None:
            # Le mode quotidien moissonne HAL seul.
            effective &= {"hal"}

        def task(source: str) -> TaskRun:
            def run(ctx: PhaseContext) -> PhaseMetrics:
                if last_daily is not None and source == "hal":
                    ctx.logger.info(
                        "%sMode incrémental : enregistrements HAL modifiés depuis le %s (%s)",
                        BRANCH,
                        date_to_french(last_daily[0]),
                        last_daily[1],
                    )
                window = HarvestWindow(
                    start_year=options.start_year if source in _YEAR_BOUNDED_SOURCES else None,
                    year=options.year,
                    since=since,
                )
                try:
                    return self.harvest_one(ctx, source, window)
                except HarvestConfigError as exc:
                    metrics = PhaseMetrics()
                    signal_source_unconfigured(
                        metrics, source, str(exc), logger=ctx.logger, phase="harvest"
                    )
                    return metrics

            return run

        def selected(source: str) -> Callable[[PhaseContext], bool]:
            return lambda _ctx: source in effective

        by_task = run_tasks(
            "harvest",
            {
                f"harvest.{source}": TaskStep(
                    task(source),
                    label=source_label(source),
                    progress_bar=True,
                    threshold=5,
                    when=selected(source),
                )
                for source in HARVESTED_SOURCES
            },
            ctx,
            parallel=self.run_parallel,
        )

        metrics = PhaseMetrics()
        by_source: dict[str, dict[str, float | None]] = {}
        for source in HARVESTED_SOURCES:
            source_metrics = by_task[f"harvest.{source}"]
            metrics.merge(source_metrics)
            if source in effective and not skipped(source_metrics):
                by_source[source] = _source_summary(source_metrics)
        if by_source:
            metrics.details["table"] = {
                "rows": [{"key": source, **summary} for source, summary in by_source.items()]
            }
        return metrics

    def _since_last_daily(self) -> tuple[date, str]:
        """Mode quotidien : date depuis laquelle HAL est moissonné, avec son origine — le dernier moissonnage quotidien réussi, ou les 30 derniers jours."""
        last = self.get_last_daily_harvest_date()
        if last is not None:
            return last, "dernier moissonnage quotidien réussi"
        return today() - timedelta(
            days=30
        ), "aucun moissonnage quotidien réussi, repli sur 30 jours"


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    registry = _harvesters()

    def harvest_one(ctx: PhaseContext, source: str, window: HarvestWindow) -> PhaseMetrics:
        return _run_harvest(ctx, source, registry[source], window)

    return HarvestPhase(
        count_extraction_structures=_extraction_structure_count,
        harvest_one=harvest_one,
        run_parallel=run_parallel,
        get_last_daily_harvest_date=get_last_daily_harvest_date,
    )


def _extraction_structure_count(ctx: PhaseContext) -> int:
    """Nombre de structures du périmètre d'extraction, lu dans `perimeter_structures`."""
    with ctx.open_tx() as conn:
        return len(get_extraction_structure_ids(conn))


def _harvesters() -> dict[str, HarvesterFactory]:
    """Constructeur du moissonneur de chaque source : `(conn, source_log)` → moissonneur câblé.

    `wos` et `scanr` lisent leurs identifiants d'API en configuration.

    Chaque constructeur importe les modules de sa source au moment où il s'exécute. Une source écartée du run ne charge donc pas son code, et un défaut qui l'atteint laisse les autres tourner."""

    def hal(conn: Connection, source_log: logging.Logger) -> Harvester:
        from pipeline.ingestion.hal.api import HalClient
        from pipeline.ingestion.hal.harvest import HalHarvester

        return HalHarvester(conn, source_log, HalClient(API_BASE_URLS["hal"]))

    def openalex(conn: Connection, source_log: logging.Logger) -> Harvester:
        from pipeline.ingestion.openalex.api import OpenalexClient
        from pipeline.ingestion.openalex.harvest import OpenalexHarvester

        return OpenalexHarvester(conn, source_log, OpenalexClient(API_BASE_URLS["openalex"]))

    def wos(conn: Connection, source_log: logging.Logger) -> Harvester:
        from pipeline.ingestion.wos.api import WosClient
        from pipeline.ingestion.wos.harvest import WosHarvester

        client = WosClient(API_BASE_URLS["wos"], api_key=get_wos_api_key())
        return WosHarvester(conn, source_log, client)

    def scanr(conn: Connection, source_log: logging.Logger) -> Harvester:
        from pipeline.ingestion.scanr.api import ScanrClient
        from pipeline.ingestion.scanr.harvest import ScanrHarvester

        client = ScanrClient(API_BASE_URLS["scanr"], credentials=get_scanr_credentials())
        return ScanrHarvester(conn, source_log, client)

    def theses(conn: Connection, source_log: logging.Logger) -> Harvester:
        from pipeline.ingestion.theses.api import ThesesClient
        from pipeline.ingestion.theses.harvest import ThesesHarvester

        return ThesesHarvester(conn, source_log, ThesesClient(API_BASE_URLS["theses"]))

    def datacite(conn: Connection, source_log: logging.Logger) -> Harvester:
        from pipeline.ingestion.datacite.api import DataciteClient
        from pipeline.ingestion.datacite.harvest import DataciteHarvester

        return DataciteHarvester(conn, source_log, DataciteClient(API_BASE_URLS["datacite"]))

    return {
        "hal": hal,
        "openalex": openalex,
        "wos": wos,
        "scanr": scanr,
        "theses": theses,
        "datacite": datacite,
    }


def _run_harvest(
    ctx: PhaseContext,
    source: str,
    make_harvester: HarvesterFactory,
    window: HarvestWindow,
) -> PhaseMetrics:
    """Déroulé commun d'une extraction : ouverture de la connexion, exécution, fermeture. `make_harvester` contient le câblage propre à la source."""
    source_log = setup_logger(source, str(PROJECT_ROOT / "logs"))
    with ctx.open_tx() as conn:
        return make_harvester(conn, source_log).run(window)
