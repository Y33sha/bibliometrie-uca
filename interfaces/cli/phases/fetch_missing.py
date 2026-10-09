"""Câblage de la phase `fetch_missing`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from application.pipeline.context import Phase
from application.pipeline.libelles import etape
from application.pipeline.metrics import PhaseMetrics
from interfaces.cli.phases.execution import credentials_missing, log, open_tx, under_circuit_breaker

if TYPE_CHECKING:
    from application.ports.pipeline.fetch_missing.doi import (
        AsyncFetchMissingDoiAdapter,
    )


def build() -> Phase:
    """Rattrapage des documents repérés dans une source mais absents d'une autre.

    La recherche dans HAL télécharge les documents que HAL détient et que le staging n'a pas, repérés par leur hal-id dans OpenAlex et ScanR, ou par le NNT d'une thèse soutenue. La recherche par DOI vise ensuite, pour chaque source cible, les DOI vus dans les autres sources et absents de la sienne. WoS est opt-in (`--include-wos`) : crédit API limité, source exclue par défaut.

    Les deux se bornent d'elles-mêmes : un identifiant cherché en vain est inscrit dans `failed_lookups`, avec un délai avant la prochaine tentative, ou définitivement quand il est natif de la source.

    Séquence, parallélisme et métriques dans `application/pipeline/fetch_missing/phase.py`.
    """
    from application.pipeline.fetch_missing.phase import FetchMissingPhase
    from infrastructure.parallel import run_parallel

    return FetchMissingPhase(
        fetch_hal_by_id=_run_fetch_missing_hal_by_id,
        fetch_hal_by_nnt=_run_fetch_missing_hal_by_nnt,
        fetch_doi_one=_run_fetch_missing_doi,
        run_parallel=run_parallel,
        credentials_missing=credentials_missing,
    )


def _run_fetch_missing_hal_by_id() -> PhaseMetrics:
    """Recherche dans HAL par hal-id (OpenAlex/ScanR) : documents absents du staging."""
    from application.pipeline.fetch_missing.hal import fetch_missing_hal_by_id
    from infrastructure.sources.config import get_fetch_missing_retry_after_days
    from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

    etape(log, "Recherche dans HAL des documents avec hal-id trouvés ailleurs")
    with open_tx() as conn:
        return asyncio.run(
            fetch_missing_hal_by_id(
                conn,
                PgHalFetchMissingAdapter(),
                log,
                retry_after_days=get_fetch_missing_retry_after_days(conn),
            )
        )


def _run_fetch_missing_hal_by_nnt() -> PhaseMetrics:
    """Recherche dans HAL par NNT (theses.fr) : thèses soutenues sans document HAL."""
    from application.pipeline.fetch_missing.hal import fetch_missing_hal_by_nnt
    from infrastructure.sources.config import get_fetch_missing_retry_after_days
    from infrastructure.sources.hal.fetch_missing_hal import PgHalFetchMissingAdapter

    etape(log, "Recherche dans HAL des thèses avec NNT trouvées ailleurs")
    with open_tx() as conn:
        return asyncio.run(
            fetch_missing_hal_by_nnt(
                conn,
                PgHalFetchMissingAdapter(),
                log,
                retry_after_days=get_fetch_missing_retry_after_days(conn),
            )
        )


def _make_fetch_missing_doi_adapter(target: str) -> AsyncFetchMissingDoiAdapter:
    """Construit l'adapter `fetch_missing_doi` d'une source cible.

    Consommé par la recherche par DOI (`_run_fetch_missing_doi`).
    """
    from typing import cast

    from infrastructure.sources.crossref.fetch_missing_doi import CrossrefFetchMissingDoiAdapter
    from infrastructure.sources.datacite.fetch_missing_doi import DataciteFetchMissingDoiAdapter
    from infrastructure.sources.hal.fetch_missing_doi import HalFetchMissingDoiAdapter
    from infrastructure.sources.openalex.fetch_missing_doi import OpenalexFetchMissingDoiAdapter
    from infrastructure.sources.scanr.fetch_missing_doi import ScanrFetchMissingDoiAdapter
    from infrastructure.sources.wos.fetch_missing_doi import WosFetchMissingDoiAdapter

    # Cast : mypy ne reconnaît pas qu'une classe concrète se conforme à un Protocol quand elle
    # est passée comme `type[Protocol]`.
    adapter_classes: dict[str, type[AsyncFetchMissingDoiAdapter]] = cast(
        "dict[str, type[AsyncFetchMissingDoiAdapter]]",
        {
            "hal": HalFetchMissingDoiAdapter,
            "openalex": OpenalexFetchMissingDoiAdapter,
            "wos": WosFetchMissingDoiAdapter,
            "scanr": ScanrFetchMissingDoiAdapter,
            "crossref": CrossrefFetchMissingDoiAdapter,
            "datacite": DataciteFetchMissingDoiAdapter,
        },
    )
    return adapter_classes[target]()


def _run_fetch_missing_doi(target: str) -> PhaseMetrics:
    from application.pipeline.fetch_missing.doi import run_async
    from infrastructure.pipeline.fetch_missing.doi import get_missing_dois
    from infrastructure.sources.config import (
        get_fetch_missing_max_per_source,
        get_fetch_missing_retry_after_days,
    )

    adapter = _make_fetch_missing_doi_adapter(target)
    with open_tx() as conn:
        retry_after_days = get_fetch_missing_retry_after_days(conn)
        limit = get_fetch_missing_max_per_source(conn)
        return under_circuit_breaker(
            target,
            lambda breaker: asyncio.run(
                run_async(
                    conn,
                    adapter,
                    log,
                    missing_dois_reader=get_missing_dois,
                    retry_after_days=retry_after_days,
                    limit=limit,
                    breaker=breaker,
                )
            ),
            phase="fetch_missing",
            logger=log,
        )
