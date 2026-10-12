"""Orchestrateur de la phase `extract` : moissonnage des sources vers le staging.

Workflow (sans I/O ni threads : ceux-ci sont injectés) :

- s'arrête en échec si le périmètre d'extraction ne contient aucune structure ;
- lit la policy du mode (`modes.py`) : sources autorisées et stratégie d'années ;
- mode `since_last` (quotidien) : HAL en incrémental depuis la dernière extraction quotidienne réussie ;
- sinon : toutes les sources retenues en parallèle, sur la plage `[start_year … courante]` (ou `--year`) ; `theses` ignore la borne large (tout l'historique des PPN, sauf `--year`) ;
- assemble les métriques par source et signale les sources non configurées.

Les dépendances techniques sont injectées par le composition-root :

- `count_extraction_structures()` : le nombre de structures du périmètre d'extraction ;
- `extract_one(source, args)` : ouvre la connexion, câble l'extracteur, exécute l'extraction sous circuit-breaker (les métriques rendues portent déjà l'éventuel signal `source_unavailable`), et lève `ExtractionConfigError` si la source n'est pas configurée ;
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
from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from pipeline.context import Phase, PhaseContext
from pipeline.execution import circuit_breaker, open_tx, signal_if_tripped
from pipeline.libelles import etape
from pipeline.metrics import PhaseMetrics
from pipeline.modes import MODES
from pipeline.parallel import RunParallel
from pipeline.signals import (
    signal_source_unavailable,
    signal_source_unconfigured,
    timed_metrics,
)
from pipeline.sources.circuit_breaker import SourceCircuitBreaker, SourceUnavailableError
from pipeline.sources.harvest import ExtractionConfigError
from pipeline.structures.perimeter import EmptyExtractionPerimeterError

if TYPE_CHECKING:
    from sqlalchemy import Connection


ExtractOne = Callable[[str, argparse.Namespace], PhaseMetrics]
GetLastDailyExtractDate = Callable[[], date | None]

# Ordre de construction des tâches parallèles (les rows de la table suivent l'ordre d'achèvement).
_PARALLEL_SOURCES = ("openalex", "hal", "wos", "scanr", "theses", "datacite")
# `theses` ne suit pas la borne d'années large : elle ramène tout l'historique des PPN (sauf --year).
_YEAR_BOUNDED_SOURCES = frozenset({"openalex", "hal", "wos", "scanr", "datacite"})


def _extractor_args(
    *, start_year: int | None = None, year: int | None = None, since: str | None = None
) -> argparse.Namespace:
    """Construit le `args` consommé par `SourceExtractor.run` (start_year, year, since). HAL et OpenAlex exploitent `since` (incrémental)."""
    return argparse.Namespace(start_year=start_year, year=year, since=since)


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
    """Issue d'une extraction de source : métriques + durée, ou motif de non-configuration / d'indisponibilité."""

    metrics: PhaseMetrics | None
    duration: float
    unconfigured: str | None = None
    unavailable: str | None = None


@dataclass(frozen=True)
class ExtractPhase:
    count_extraction_structures: Callable[[], int]
    extract_one: ExtractOne
    run_parallel: RunParallel
    get_last_daily_extract_date: GetLastDailyExtractDate

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Retient les sources effectives selon le mode, les extrait, et assemble les métriques."""
        options, logger = ctx.options, ctx.logger
        if self.count_extraction_structures() == 0:
            raise EmptyExtractionPerimeterError()
        policy = MODES[options.mode]
        effective = set(policy.extract_sources) | ({"wos"} if options.include_wos else set())
        if options.sources:
            effective &= options.sources
        metrics = PhaseMetrics()

        if policy.year_selection == "since_last":
            by_source = _run_since_last(
                effective, self.extract_one, self.get_last_daily_extract_date, metrics, logger
            )
        else:
            by_source = _run_parallel_sources(
                effective,
                options.year,
                options.start_year,
                self.extract_one,
                self.run_parallel,
                metrics,
                logger,
            )

        if by_source:
            metrics.details["table"] = {
                "rows": [{"key": source, **summary} for source, summary in by_source.items()]
            }
        return metrics


def _run_since_last(
    effective: set[str],
    extract_one: ExtractOne,
    get_last_daily_extract_date: GetLastDailyExtractDate,
    metrics: PhaseMetrics,
    logger: logging.Logger,
) -> dict[str, dict[str, float]]:
    """Mode quotidien : HAL depuis la dernière extraction quotidienne réussie, ou les 30 derniers jours."""
    last = get_last_daily_extract_date()
    if last is not None:
        depuis = last
        origine = "dernière extraction quotidienne réussie"
    else:
        depuis = today() - timedelta(days=30)
        origine = "aucune extraction quotidienne réussie, repli sur 30 jours"
    since = depuis.isoformat()
    logger.info(
        "Mode incrémental : notices HAL modifiées depuis le %s (%s)",
        date_to_french(depuis),
        origine,
    )

    if "hal" not in effective:
        return {}
    try:
        hal_metrics, hal_duration = timed_metrics(
            lambda: extract_one("hal", _extractor_args(since=since))
        )
    except ExtractionConfigError as exc:
        signal_source_unconfigured(metrics, "hal", str(exc), logger=logger, phase="extract")
        return {}
    except SourceUnavailableError:
        signal_source_unavailable(metrics, "hal", logger=logger, phase="extract")
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

    etape(logger, "Extraction des sources")
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
        if outcome.unavailable is not None:
            signal_source_unavailable(metrics, source, logger=logger, phase="extract")
            continue
        assert outcome.metrics is not None
        metrics.merge(outcome.metrics)
        by_source[source] = _source_summary(outcome.metrics, outcome.duration)
    return by_source


def _extraction_thunk(
    extract_one: ExtractOne, source: str, args: argparse.Namespace
) -> Callable[[], _SourceOutcome]:
    """Enveloppe une extraction en thunk : chronométrée, la non-configuration rendue en valeur (jamais levée hors du thread) pour que le primitif de parallélisme n'ait pas à la connaître."""

    def thunk() -> _SourceOutcome:
        try:
            source_metrics, duration = timed_metrics(lambda: extract_one(source, args))
        except ExtractionConfigError as exc:
            return _SourceOutcome(None, 0.0, unconfigured=str(exc))
        except SourceUnavailableError as exc:
            return _SourceOutcome(None, 0.0, unavailable=str(exc))
        return _SourceOutcome(source_metrics, duration)

    return thunk


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

    `pipeline/modes.py` définit la policy du mode : sources retenues et stratégie d'années. Séquence, parallélisme et métriques dans `pipeline/sources/extract.py` ; ici, le câblage : registre des extracteurs, primitif de parallélisme, lecture de la date de dernière extraction.
    """
    from infrastructure.observability.phase_executions import get_last_daily_extract_date
    from pipeline.parallel import run_parallel

    registry = _extractors()

    def extract_one(source: str, args: argparse.Namespace) -> PhaseMetrics:
        return _run_extract(source, registry[source], args)

    return ExtractPhase(
        count_extraction_structures=_extraction_structure_count,
        extract_one=extract_one,
        run_parallel=run_parallel,
        get_last_daily_extract_date=get_last_daily_extract_date,
    )


def _extraction_structure_count() -> int:
    """Nombre de structures du périmètre d'extraction, lu dans `perimeter_structures`."""
    from pipeline.structures.perimeter import PerimeterQueries

    with open_tx() as conn:
        return PerimeterQueries().count_extraction_structures(conn)


def _run_extractor(source: str, extractor: Extracteur, args: argparse.Namespace) -> PhaseMetrics:
    """Exécute un extracteur sous circuit-breaker, qui coupe la source après cinq échecs.

    Le circuit-breaker est posé dans la ContextVar que lit le client HTTP synchrone, et passé à `run`, dont les boucles le consultent pour arrêter une source à bout de budget. Le seuil est plus bas qu'à la phase `fetch_missing`, les extracteurs travaillant sans lots concurrents.
    """
    with circuit_breaker(source, threshold=5) as breaker:
        metrics = extractor.run(args, breaker=breaker)
    signal_if_tripped(metrics, breaker)
    return metrics


def _extractors() -> dict[str, ConstructeurExtracteur]:
    """Constructeur de l'extracteur de chaque source : `(conn, source_log)` → extracteur câblé.

    `wos` et `scanr` lisent leurs identifiants d'API en configuration.

    Chaque constructeur importe les modules de sa source au moment où il s'exécute. Une source écartée du run ne charge donc pas son code, et un défaut qui l'atteint laisse les autres tourner."""
    from pipeline.sources.api_params import API_BASE_URLS

    def hal(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.sources.hal.harvest import HalClient, HalExtractor

        return HalExtractor(conn, source_log, HalClient(API_BASE_URLS["hal"]))

    def openalex(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.sources.openalex.harvest import OpenalexClient, OpenalexExtractor

        return OpenalexExtractor(conn, source_log, OpenalexClient(API_BASE_URLS["openalex"]))

    def wos(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.config import get_wos_api_key
        from pipeline.sources.wos.harvest import WosClient, WosExtractor

        client = WosClient(API_BASE_URLS["wos"], api_key=get_wos_api_key())
        return WosExtractor(conn, source_log, client)

    def scanr(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.config import get_scanr_credentials
        from pipeline.sources.scanr.harvest import ScanrClient, ScanrExtractor

        client = ScanrClient(API_BASE_URLS["scanr"], credentials=get_scanr_credentials())
        return ScanrExtractor(conn, source_log, client)

    def theses(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.sources.theses.harvest import ThesesClient, ThesesExtractor

        return ThesesExtractor(conn, source_log, ThesesClient(API_BASE_URLS["theses"]))

    def datacite(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.sources.datacite.harvest import DataciteClient, DataciteExtractor

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
    source: str, make_extractor: ConstructeurExtracteur, args: argparse.Namespace
) -> PhaseMetrics:
    """Déroulé commun d'une extraction : ouverture de la connexion, exécution sous circuit-breaker, fermeture. `make_extractor` contient le câblage propre à la source."""
    source_log = setup_logger(source, str(PROJECT_ROOT / "logs"))
    with open_tx() as conn:
        return _run_extractor(source, make_extractor(conn, source_log), args)
