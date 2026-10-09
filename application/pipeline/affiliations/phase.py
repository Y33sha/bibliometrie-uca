"""Orchestrateur de la phase `affiliations` : résolution des affiliations sur les `source_authorships`.

Quatre sous-étapes, chacune dans sa propre transaction :

0. **refresh_ror** — importe la dernière version du dump ROR si elle n'est pas déjà importée (`refresh_ror.py`). Le runner est injecté par le composition root.
1. **refresh_perimeter_structures** — rafraîchit la table `perimeter_structures`. La phase s'arrête en échec si le périmètre d'extraction ne contient aucune structure.
2. **resolve_addresses** — matche les adresses vers les structures connues (commits par lots).
3. **populate_affiliations** — pose `in_perimeter` sur les `source_authorships` depuis les adresses résolues.
"""

from collections.abc import Callable
from dataclasses import dataclass

from application.pipeline.affiliations.populate_affiliations import run_populate
from application.pipeline.affiliations.resolve_addresses import run_resolution
from application.pipeline.context import PhaseContext
from application.pipeline.libelles import etape
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.affiliations.address_resolution import AddressResolutionQueries
from application.ports.pipeline.affiliations.in_perimeter import AffiliationsQueries
from application.ports.pipeline.perimeter_structures import (
    EmptyExtractionPerimeterError,
    PerimeterStructuresQueries,
)


@dataclass(frozen=True)
class AffiliationsPhase:
    address_queries: AddressResolutionQueries
    affiliations_queries: AffiliationsQueries
    perimeter_queries: PerimeterStructuresQueries
    refresh_ror: Callable[[], PhaseMetrics]

    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Enchaîne les quatre sous-étapes et assemble les métriques de la phase."""
        open_tx, logger, perimeter_queries = ctx.open_tx, ctx.logger, self.perimeter_queries
        ror = self.refresh_ror()

        with open_tx() as conn:
            perimeter_queries.refresh_perimeter_structures(conn)
            if perimeter_queries.count_extraction_structures(conn) == 0:
                raise EmptyExtractionPerimeterError()

        etape(logger, "Identification des structures dans les adresses institutionnelles")
        with open_tx() as conn:
            # Périmètre lu une fois après le refresh, réutilisé par les deux sous-étapes suivantes.
            perimeter_ids = set(perimeter_queries.get_persons_structure_ids_list(conn))
            stats = run_resolution(conn, self.address_queries, perimeter_ids, logger)

        metrics = PhaseMetrics()
        metrics.add(total=stats.processed)
        metrics.details["summary"] = {
            "adresses": stats.processed,
            "in_perimeter": stats.in_perimeter,
        }
        metrics.details.update(ror.details)

        etape(logger, "Rattachement des structures aux auteurs des documents")
        with open_tx() as conn:
            run_populate(conn, self.affiliations_queries, logger, perimeter_ids)

        metrics.resume = ""
        return metrics
