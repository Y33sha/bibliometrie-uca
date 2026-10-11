"""Câblage de la phase `extract` et registre des extracteurs."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from infrastructure.sources.circuit_breaker import SourceCircuitBreaker
from interfaces.cli.phases.execution import circuit_breaker, open_tx, signal_if_tripped
from pipeline.context import Phase
from pipeline.metrics import PhaseMetrics

if TYPE_CHECKING:
    from sqlalchemy import Connection


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
    from infrastructure.parallel import run_parallel
    from pipeline.sources.extract import ExtractPhase

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
    from infrastructure.pipeline.perimeter import PgPerimeterStructuresQueries

    with open_tx() as conn:
        return PgPerimeterStructuresQueries().count_extraction_structures(conn)


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
    from infrastructure.sources.api_params import API_BASE_URLS

    def hal(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.sources.hal.harvest import HalClient, HalExtractor

        return HalExtractor(conn, source_log, HalClient(API_BASE_URLS["hal"]))

    def openalex(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from pipeline.sources.openalex.harvest import OpenalexClient, OpenalexExtractor

        return OpenalexExtractor(conn, source_log, OpenalexClient(API_BASE_URLS["openalex"]))

    def wos(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from infrastructure.sources.config import get_wos_api_key
        from pipeline.sources.wos.harvest import WosClient, WosExtractor

        client = WosClient(API_BASE_URLS["wos"], api_key=get_wos_api_key())
        return WosExtractor(conn, source_log, client)

    def scanr(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from infrastructure.sources.config import get_scanr_credentials
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
