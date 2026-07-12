"""Orchestrateur de la phase `affiliations` : résolution des affiliations sur les `source_authorships`.

Trois sous-étapes, chacune dans sa propre transaction :

1. **refresh_perimeter_structures** — rafraîchit la table `perimeter_structures`.
2. **resolve_addresses** — matche les adresses vers les structures connues (commits par lots).
3. **populate_affiliations** — pose `in_perimeter` sur les `source_authorships` depuis les adresses résolues.
"""

import logging
import time

from application.pipeline.affiliations.populate_affiliations import run_populate
from application.pipeline.affiliations.resolve_addresses import run_resolution
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.address_resolution import AddressResolutionQueries
from application.ports.pipeline.affiliations import AffiliationsQueries
from application.ports.pipeline.perimeter import PerimeterQueries
from application.ports.pipeline.transaction import OpenTransaction


def run(
    open_tx: OpenTransaction,
    address_queries: AddressResolutionQueries,
    affiliations_queries: AffiliationsQueries,
    perimeter_queries: PerimeterQueries,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Enchaîne les trois sous-étapes et assemble les métriques de la phase."""
    logger.info("▶ refresh perimeter_structures")
    t0 = time.perf_counter()
    with open_tx() as conn:
        n_links = perimeter_queries.refresh_perimeter_structures(conn)
    logger.info("✓ perimeter_structures : %d liens en %.1fs", n_links, time.perf_counter() - t0)

    logger.info("▶ resolve_addresses")
    t0 = time.perf_counter()
    with open_tx() as conn:
        # Périmètre lu une fois après le refresh, réutilisé par les deux sous-étapes suivantes.
        perimeter_ids = set(perimeter_queries.get_persons_structure_ids_list(conn))
        stats = run_resolution(conn, address_queries, perimeter_ids, logger)
    logger.info("✓ resolve_addresses terminé en %.1fs", time.perf_counter() - t0)

    metrics = PhaseMetrics()
    metrics.add(total=stats.processed)
    metrics.details["summary"] = {"adresses": stats.processed, "in_perimeter": stats.in_perimeter}

    logger.info("▶ populate_affiliations")
    t0 = time.perf_counter()
    with open_tx() as conn:
        run_populate(conn, affiliations_queries, logger, perimeter_ids)
    logger.info("✓ populate_affiliations terminé en %.1fs", time.perf_counter() - t0)

    return metrics
