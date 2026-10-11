"""Câblage de la phase `fetch_stale`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from interfaces.cli.phases.execution import credentials_missing, log, open_tx, under_circuit_breaker
from pipeline.context import Phase
from pipeline.metrics import PhaseMetrics

if TYPE_CHECKING:
    from pipeline.sources.fetch_stale import StaleRefetch


def build() -> Phase:
    """Rafraîchit les rows à `last_seen_at` ancien et marque les disparues.

    Chaque row est réinterrogée par son identifiant natif (`staging.source_id`), avec ou sans DOI : trouvée, son `last_seen_at` et son `raw_data` sont rafraîchis ; absente de sa source, elle reçoit un `disappeared_at` ; sur échec réseau, elle attend le run suivant. Le délai `fetch_stale_after_days` étale la charge, chaque passe ramassant seulement les rows qui viennent de le franchir.

    Le mode `daily` saute la phase. La fenêtre d'années du run (`start_year`/`year`, via `source_publications.pub_year`) borne le rafraîchissement aux années que le run moissonne. `theses` ramène tout son historique, comme à l'extraction, sauf sous `--year`. WoS est opt-in (`--include-wos`).

    Séquence et métriques dans `pipeline/sources/fetch_stale.py`.
    """
    from pipeline.sources.fetch_stale import FetchStalePhase

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


def _make_refetch(source: str) -> StaleRefetch:
    """Construit la nouvelle lecture par identifiant natif d'une source."""
    from pipeline.sources.crossref.fetch_stale import CrossrefStaleRefetch
    from pipeline.sources.datacite.fetch_stale import DataciteStaleRefetch
    from pipeline.sources.hal.fetch_stale import HalStaleRefetch
    from pipeline.sources.openalex.fetch_stale import OpenalexStaleRefetch
    from pipeline.sources.scanr.fetch_stale import ScanrStaleRefetch
    from pipeline.sources.theses.fetch_stale import ThesesStaleRefetch
    from pipeline.sources.wos.fetch_stale import WosStaleRefetch

    refetches: dict[str, type[StaleRefetch]] = {
        "hal": HalStaleRefetch,
        "openalex": OpenalexStaleRefetch,
        "wos": WosStaleRefetch,
        "scanr": ScanrStaleRefetch,
        "theses": ThesesStaleRefetch,
        "crossref": CrossrefStaleRefetch,
        "datacite": DataciteStaleRefetch,
    }
    return refetches[source]()


def _run_fetch_stale(target: str, years: list[int] | None) -> PhaseMetrics:
    """Refetch par id natif des rows stale d'une source : trouvé → bump, absence → disappeared.

    `years` borne le refresh à la fenêtre d'années du run (None = tout le stale).
    """
    from infrastructure.sources.config import get_fetch_stale_after_days
    from pipeline.sources.fetch_stale import refresh

    refetch = _make_refetch(target)
    with open_tx() as conn:
        after_days = get_fetch_stale_after_days(conn)
        return under_circuit_breaker(
            target,
            lambda breaker: asyncio.run(
                refresh(conn, refetch, log, after_days=after_days, years=years, breaker=breaker)
            ),
            phase="fetch_stale",
            logger=log,
        )
