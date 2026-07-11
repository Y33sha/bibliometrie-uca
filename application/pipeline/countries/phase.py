"""Orchestrateur de la phase `countries` : détection du pays des adresses et recalcul en cascade.

Quatre sous-étapes, chacune dans sa propre transaction, encadrées d'un bilan initial et final :

1. **detect_by_country_name** — pays déduit du dernier segment de l'adresse (nom de pays).
2. **detect_by_place_name** — pays déduit d'un nom de lieu (institution, ville).
3. **suggest_address_countries** — suggestion floue (commits par lots). `retry_empty` (mode `full`) réessaie les adresses tentées sans match.
4. **refresh_publication_countries** — recalcul des caches dénormalisés (source_publications, publications) depuis `addresses.countries`.

Le bilan (initial/final) trace l'entonnoir : du manque initial en pays aux pays rattachés par le run, puis au reste (dont une part porte une suggestion).
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy import Connection

from application.pipeline.countries import (
    detect_by_country_name,
    detect_by_place_name,
    refresh_publication_countries,
    suggest_countries,
)
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.countries import AddressCountryStatus, CountryQueries
from application.ports.pipeline.transaction import OpenTransaction


def _bilan(
    open_tx: OpenTransaction, queries: CountryQueries, logger: logging.Logger, label: str
) -> AddressCountryStatus:
    """Bilan global de l'état pays des adresses, logué en début et fin de phase."""
    with open_tx() as conn:
        s = queries.count_address_country_status(conn)
    logger.info(
        "%s — adresses (pub_count > 0) : %d total | %d avec pays | %d avec suggestion | %d sans rien",
        label,
        s.total,
        s.with_country,
        s.with_suggestion,
        s.none,
    )
    return s


def _timed_metrics_step(
    open_tx: OpenTransaction,
    label: str,
    step: Callable[[Connection], PhaseMetrics],
    logger: logging.Logger,
    *,
    start_suffix: str = "",
) -> PhaseMetrics:
    """Exécute une sous-étape (rendant des `PhaseMetrics`) dans sa transaction, chronométrée."""
    logger.info("▶ %s%s", label, start_suffix)
    t0 = time.perf_counter()
    with open_tx() as conn:
        metrics = step(conn)
    logger.info("✓ %s terminé en %.1fs — %s", label, time.perf_counter() - t0, metrics.as_summary())
    return metrics


def run(
    open_tx: OpenTransaction,
    queries: CountryQueries,
    logger: logging.Logger,
    *,
    retry_empty: bool,
) -> PhaseMetrics:
    """Enchaîne les quatre sous-étapes, borne l'entonnoir par les bilans et assemble les métriques."""
    metrics = PhaseMetrics()
    initial = _bilan(open_tx, queries, logger, "Bilan initial")

    metrics.merge(
        _timed_metrics_step(
            open_tx,
            "detect_by_country_name",
            lambda conn: detect_by_country_name.run(conn, queries, logger),
            logger,
        )
    )
    metrics.merge(
        _timed_metrics_step(
            open_tx,
            "detect_by_place_name",
            lambda conn: detect_by_place_name.run(conn, queries, logger),
            logger,
        )
    )
    metrics.merge(
        _timed_metrics_step(
            open_tx,
            "suggest_address_countries",
            lambda conn: suggest_countries.run(conn, queries, logger, retry_empty=retry_empty),
            logger,
            start_suffix=" (retry-vides)" if retry_empty else "",
        )
    )

    logger.info("▶ refresh_publication_countries")
    t0 = time.perf_counter()
    with open_tx() as conn:
        refresh_publication_countries.refresh(conn, queries, logger)
    logger.info("✓ refresh_publication_countries terminé en %.1fs", time.perf_counter() - t0)

    final = _bilan(open_tx, queries, logger, "Bilan final")
    # Entonnoir : du manque initial (adresses sans pays avant la détection du run) aux pays rattachés par le run, puis au reste (dont une part porte une suggestion).
    total = final.total
    without_initial = total - initial.with_country
    metrics.details["summary"] = {
        "total": total,
        "without_initial": without_initial,
        "without_pct": round(100 * without_initial / total, 1) if total else 0,
        "newly_attached": final.with_country - initial.with_country,
        "remaining": total - final.with_country,
        "with_suggestion": final.with_suggestion,
    }
    return metrics
