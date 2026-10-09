"""Câblage de la phase `fetch_stale`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from application.pipeline.context import Phase
from application.pipeline.metrics import PhaseMetrics
from interfaces.cli.phases.execution import credentials_missing, log, open_tx, under_circuit_breaker

if TYPE_CHECKING:
    from application.ports.pipeline.extract.fetch_stale import FetchStaleAdapter


def build() -> Phase:
    """Rafraîchit les rows à `last_seen_at` ancien et marque les disparues.

    Chaque row est réinterrogée par son identifiant natif (`staging.source_id`), avec ou sans DOI : trouvée, son `last_seen_at` et son `raw_data` sont rafraîchis ; absente de sa source, elle reçoit un `disappeared_at` ; sur échec réseau, elle attend le run suivant. Le délai `fetch_stale_after_days` étale la charge, chaque passe ramassant seulement les rows qui viennent de le franchir.

    Le mode `daily` saute la phase. La fenêtre d'années du run (`start_year`/`year`, via `source_publications.pub_year`) borne le rafraîchissement aux années que le run moissonne. `theses` ramène tout son historique, comme à l'extraction, sauf sous `--year`. WoS est opt-in (`--include-wos`).

    Séquence et métriques dans `application/pipeline/extract/fetch_stale.py::FetchStalePhase`.
    """
    from application.pipeline.extract.fetch_stale import FetchStalePhase

    return FetchStalePhase(
        refresh_one=_run_fetch_stale,
        credentials_missing=credentials_missing,
        get_years_for_window=_get_years_for_window,
    )


def _get_years_for_window(start_year: int | None) -> list[int] | None:
    """Années de la fenêtre du run, de `start_year` à l'année courante."""
    from infrastructure.sources.config import get_years

    with open_tx() as conn:
        return get_years(conn, start_year)


def _make_fetch_stale_adapter(source: str) -> FetchStaleAdapter:
    """Construit l'adapter `fetch_stale` d'une source (refetch par id natif)."""
    from infrastructure.sources.crossref.fetch_stale import CrossrefFetchStaleAdapter
    from infrastructure.sources.datacite.fetch_stale import DataciteFetchStaleAdapter
    from infrastructure.sources.hal.fetch_stale import HalFetchStaleAdapter
    from infrastructure.sources.openalex.fetch_stale import OpenalexFetchStaleAdapter
    from infrastructure.sources.scanr.fetch_stale import ScanrFetchStaleAdapter
    from infrastructure.sources.theses.fetch_stale import ThesesFetchStaleAdapter
    from infrastructure.sources.wos.fetch_stale import WosFetchStaleAdapter

    # Cast : mypy ne reconnaît pas qu'une classe concrète se conforme à un Protocol quand elle
    # est passée comme `type[Protocol]`.
    adapter_classes: dict[str, type[FetchStaleAdapter]] = cast(
        "dict[str, type[FetchStaleAdapter]]",
        {
            "hal": HalFetchStaleAdapter,
            "openalex": OpenalexFetchStaleAdapter,
            "wos": WosFetchStaleAdapter,
            "scanr": ScanrFetchStaleAdapter,
            "theses": ThesesFetchStaleAdapter,
            "crossref": CrossrefFetchStaleAdapter,
            "datacite": DataciteFetchStaleAdapter,
        },
    )
    return adapter_classes[source]()


def _run_fetch_stale(target: str, years: list[int] | None) -> PhaseMetrics:
    """Refetch par id natif des rows stale d'une source : trouvé → bump, absence → disappeared.

    `years` borne le refresh à la fenêtre d'années du run (None = tout le stale).
    """
    from application.pipeline.extract.fetch_stale import refresh
    from infrastructure.sources.config import get_fetch_stale_after_days

    adapter = _make_fetch_stale_adapter(target)
    with open_tx() as conn:
        after_days = get_fetch_stale_after_days(conn)
        return under_circuit_breaker(
            target,
            lambda breaker: asyncio.run(
                refresh(conn, adapter, log, after_days=after_days, years=years, breaker=breaker)
            ),
            phase="fetch_stale",
            logger=log,
        )
