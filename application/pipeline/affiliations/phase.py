"""Orchestrateur de la phase `affiliations` : résolution des affiliations sur les `source_authorships`.

Trois sous-étapes, chacune dans sa propre transaction :

1. **refresh_perimeter_structures** — rafraîchit la table `perimeter_structures`.
2. **resolve_addresses** — matche les adresses vers les structures connues (commits par lots).
3. **populate_affiliations** — pose `in_perimeter` sur les `source_authorships` depuis les adresses résolues.
"""

import logging

from application.pipeline.affiliations.populate_affiliations import run_populate
from application.pipeline.affiliations.resolve_addresses import run_resolution
from application.pipeline.libelles import etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.affiliations.address_resolution import AddressResolutionQueries
from application.ports.pipeline.affiliations.in_perimeter import AffiliationsQueries
from application.ports.pipeline.perimeter_structures import PerimeterStructuresQueries
from application.ports.pipeline.transaction import OpenTransaction


def run(
    open_tx: OpenTransaction,
    address_queries: AddressResolutionQueries,
    affiliations_queries: AffiliationsQueries,
    perimeter_queries: PerimeterStructuresQueries,
    logger: logging.Logger,
) -> PhaseMetrics:
    """Enchaîne les trois sous-étapes et assemble les métriques de la phase."""
    with open_tx() as conn:
        perimeter_queries.refresh_perimeter_structures(conn)

    etape(logger, "Identification des structures dans les adresses institutionnelles")
    with open_tx() as conn:
        # Périmètre lu une fois après le refresh, réutilisé par les deux sous-étapes suivantes.
        perimeter_ids = set(perimeter_queries.get_persons_structure_ids_list(conn))
        stats = run_resolution(conn, address_queries, perimeter_ids, logger)

    metrics = PhaseMetrics()
    metrics.add(total=stats.processed)
    metrics.details["summary"] = {"adresses": stats.processed, "in_perimeter": stats.in_perimeter}

    etape(logger, "Rattachement des structures aux auteurs des documents")
    with open_tx() as conn:
        run_populate(conn, affiliations_queries, logger, perimeter_ids)

    metrics.resume = ""
    return metrics
