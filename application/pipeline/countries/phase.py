"""Orchestrateur de la phase `countries` : détection du pays des adresses et recalcul en cascade.

Quatre sous-étapes, chacune dans sa propre transaction :

1. **detect_by_country_name** — pays déduit du dernier segment de l'adresse (nom de pays).
2. **detect_by_place_name** — pays déduit d'un nom de lieu (institution, ville).
3. **suggest_address_countries** — suggestion floue (commits par lots). `retry_empty` (mode `full`) réessaie les adresses tentées sans match.
4. **refresh_publication_countries** — recalcul des caches dénormalisés (source_publications, publications) depuis `addresses.countries`.

L'état pays des adresses est relevé avant et après le passage : l'entonnoir qui s'en déduit — manque initial, pays rattachés par le run, reste — alimente l'observabilité de la phase. Chaque sous-étape dit au journal ce qu'elle a résolu.
"""

import logging

from application.pipeline.countries import (
    detect_by_country_name,
    detect_by_place_name,
    refresh_publication_countries,
    suggest_countries,
)
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.countries import AddressCountryStatus, CountryQueries
from application.ports.pipeline.transaction import OpenTransaction


def _etat_des_adresses(open_tx: OpenTransaction, queries: CountryQueries) -> AddressCountryStatus:
    """Relève combien d'adresses portent un pays, une suggestion, ou rien."""
    with open_tx() as conn:
        return queries.count_address_country_status(conn)


def run(
    open_tx: OpenTransaction,
    queries: CountryQueries,
    logger: logging.Logger,
    *,
    retry_empty: bool,
) -> PhaseMetrics:
    """Enchaîne les quatre sous-étapes, borne l'entonnoir par les deux relevés et assemble les métriques."""
    metrics = PhaseMetrics()
    initial = _etat_des_adresses(open_tx, queries)

    with open_tx() as conn:
        metrics.merge(detect_by_country_name.run(conn, queries, logger))
    with open_tx() as conn:
        metrics.merge(detect_by_place_name.run(conn, queries, logger))
    with open_tx() as conn:
        metrics.merge(suggest_countries.run(conn, queries, logger, retry_empty=retry_empty))
    with open_tx() as conn:
        refresh_publication_countries.refresh(conn, queries, logger)

    final = _etat_des_adresses(open_tx, queries)
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
    # Chaque sous-étape porte ce qu'elle a résolu : une ligne de clôture les répéterait.
    metrics.resume = ""
    return metrics
