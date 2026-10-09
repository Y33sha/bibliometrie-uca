"""Câblage de la phase `extract` et registre des extracteurs."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from application.pipeline.context import Phase
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.circuit_breaker import CircuitBreaker
from infrastructure import PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from interfaces.cli.phases.execution import circuit_breaker, open_tx, signal_if_tripped

if TYPE_CHECKING:
    from sqlalchemy import Connection


class Extracteur(Protocol):
    """Point d'entrée commun des extracteurs, seul que l'orchestrateur appelle.

    Chaque source a son type de configuration et son type d'adapter ; ce protocole les laisse aux extracteurs.
    """

    def run(
        self,
        args: argparse.Namespace,
        *,
        breaker: CircuitBreaker | None = None,
    ) -> PhaseMetrics: ...


# Un extracteur se construit sur la connexion de sa phase et le journal scopé à sa source.
type ConstructeurExtracteur = Callable[[Connection, logging.Logger], Extracteur]


def build() -> Phase:
    """Extraction des sources vers staging.

    `application/pipeline/modes.py` définit la policy du mode : sources retenues et stratégie d'années. Séquence, parallélisme et métriques dans `application/pipeline/extract/phase.py` ; ici, le câblage : registre des adaptateurs, primitif de parallélisme, lecture de la date de dernière extraction.
    """
    from application.pipeline.extract.phase import ExtractPhase
    from infrastructure.observability.phase_executions import get_last_daily_extract_date
    from infrastructure.parallel import run_parallel

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

    `wos` et `scanr` ouvrent une connexion d'amorçage pour lire leurs identifiants avant l'extraction ; les autres lisent leur URL de base en configuration.

    Chaque constructeur importe les modules de sa source au moment où il s'exécute. Une source écartée du run ne charge donc pas son code, et un défaut qui l'atteint laisse les autres tourner."""
    from infrastructure.sources.api_params import API_BASE_URLS

    def hal(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_hal import HalExtractor
        from infrastructure.sources.hal.extract_hal import PgHalExtractAdapter

        adapter = PgHalExtractAdapter(base_url=API_BASE_URLS["hal"])
        return HalExtractor(conn, source_log, adapter)

    def openalex(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_openalex import OpenalexExtractor
        from infrastructure.sources.openalex.extract_openalex import PgOpenalexExtractAdapter

        adapter = PgOpenalexExtractAdapter(base_url=API_BASE_URLS["openalex"])
        return OpenalexExtractor(conn, source_log, adapter)

    def wos(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_wos import WosExtractor
        from infrastructure.sources.config import get_wos_api_key
        from infrastructure.sources.wos.extract_wos import PgWosExtractAdapter

        adapter = PgWosExtractAdapter(base_url=API_BASE_URLS["wos"], api_key=get_wos_api_key())
        return WosExtractor(conn, source_log, adapter)

    def scanr(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_scanr import ScanrExtractor
        from infrastructure.sources.config import get_scanr_credentials
        from infrastructure.sources.scanr.extract_scanr import PgScanrExtractAdapter

        adapter = PgScanrExtractAdapter(
            base_url=API_BASE_URLS["scanr"], credentials=get_scanr_credentials()
        )
        return ScanrExtractor(conn, source_log, adapter)

    def theses(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_theses import ThesesExtractor
        from infrastructure.sources.theses.extract_theses import PgThesesExtractAdapter

        adapter = PgThesesExtractAdapter(base_url=API_BASE_URLS["theses"])
        return ThesesExtractor(conn, source_log, adapter)

    def datacite(conn: Connection, source_log: logging.Logger) -> Extracteur:
        from application.pipeline.extract.extract_datacite import DataciteExtractor
        from infrastructure.sources.datacite.extract_datacite import PgDataciteExtractAdapter

        adapter = PgDataciteExtractAdapter(base_url=API_BASE_URLS["datacite"])
        return DataciteExtractor(conn, source_log, adapter)

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
