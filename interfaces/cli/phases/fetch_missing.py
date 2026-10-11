"""Câblage de la phase `fetch_missing`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from interfaces.cli.phases.execution import credentials_missing, log, open_tx, under_circuit_breaker
from pipeline.context import Phase
from pipeline.metrics import PhaseMetrics

if TYPE_CHECKING:
    from pipeline.sources.fetch_missing import DoiSearch


def build() -> Phase:
    """Rattrapage des documents repérés dans une source mais absents d'une autre.

    La recherche dans HAL télécharge les documents que HAL détient et que le staging n'a pas, repérés par leur hal-id dans OpenAlex et ScanR, ou par le NNT d'une thèse soutenue. La recherche par DOI vise ensuite, pour chaque source cible, les DOI vus dans les autres sources et absents de la sienne. WoS est opt-in (`--include-wos`) : crédit API limité, source exclue par défaut.

    Les deux se bornent d'elles-mêmes : un identifiant cherché en vain est inscrit dans `failed_lookups`, avec un délai avant la prochaine tentative, ou définitivement quand il est natif de la source.

    Séquence, parallélisme et métriques dans `pipeline/sources/fetch_missing.py`.
    """
    from infrastructure.parallel import run_parallel
    from pipeline.sources.fetch_missing import FetchMissingPhase

    return FetchMissingPhase(
        fetch_hal_by_id=_run_fetch_missing_hal_by_id,
        fetch_hal_by_nnt=_run_fetch_missing_hal_by_nnt,
        fetch_doi_one=_run_fetch_missing_doi,
        run_parallel=run_parallel,
        credentials_missing=credentials_missing,
    )


def _run_fetch_missing_hal_by_id() -> PhaseMetrics:
    """Recherche dans HAL par hal-id (OpenAlex/ScanR) : documents absents du staging."""
    from infrastructure.sources.config import get_fetch_missing_retry_after_days
    from pipeline.sources.hal.fetch_missing import fetch_missing_hal_by_id

    with open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        return under_circuit_breaker(
            "hal",
            lambda _breaker: asyncio.run(
                fetch_missing_hal_by_id(conn, log, retry_after_days=retry_after_days)
            ),
            phase="fetch_missing",
            logger=log,
        )


def _run_fetch_missing_hal_by_nnt() -> PhaseMetrics:
    """Recherche dans HAL par NNT (theses.fr) : thèses soutenues sans document HAL."""
    from infrastructure.sources.config import get_fetch_missing_retry_after_days
    from pipeline.sources.hal.fetch_missing import fetch_missing_hal_by_nnt

    with open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        return under_circuit_breaker(
            "hal",
            lambda _breaker: asyncio.run(
                fetch_missing_hal_by_nnt(conn, log, retry_after_days=retry_after_days)
            ),
            phase="fetch_missing",
            logger=log,
        )


def _make_doi_search(target: str) -> DoiSearch:
    """Construit la recherche par DOI d'une source cible."""
    from pipeline.sources.crossref.fetch_missing import CrossrefDoiSearch
    from pipeline.sources.datacite.fetch_missing import DataciteDoiSearch
    from pipeline.sources.hal.fetch_missing import HalDoiSearch
    from pipeline.sources.openalex.fetch_missing import OpenalexDoiSearch
    from pipeline.sources.scanr.fetch_missing import ScanrDoiSearch
    from pipeline.sources.wos.fetch_missing import WosDoiSearch

    searches: dict[str, type[DoiSearch]] = {
        "hal": HalDoiSearch,
        "openalex": OpenalexDoiSearch,
        "wos": WosDoiSearch,
        "scanr": ScanrDoiSearch,
        "crossref": CrossrefDoiSearch,
        "datacite": DataciteDoiSearch,
    }
    return searches[target]()


def _run_fetch_missing_doi(target: str) -> PhaseMetrics:
    from infrastructure.sources.config import (
        get_fetch_missing_max_per_source,
        get_fetch_missing_retry_after_days,
    )
    from pipeline.sources.fetch_missing import fetch_missing_doi

    search = _make_doi_search(target)
    with open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        limit = get_fetch_missing_max_per_source(conn)
        return under_circuit_breaker(
            target,
            lambda breaker: asyncio.run(
                fetch_missing_doi(
                    conn,
                    search,
                    log,
                    retry_after_days=retry_after_days,
                    limit=limit,
                    breaker=breaker,
                )
            ),
            phase="fetch_missing",
            logger=log,
        )
