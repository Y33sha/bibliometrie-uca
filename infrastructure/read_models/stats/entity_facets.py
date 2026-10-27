"""Facette d'entité contextuelle (éditeur, revue, organisation partenaire) pour le tableau de bord.

Renvoie les N premières entités par volume, calculées **sous les filtres actifs** (en sautant le filtre de la dimension demandée, pour qu'une sélection ne réduise pas ses propres options). Les autres filtres — dont l'autre entité — sont inclus : sélectionner une revue restreint donc les éditeurs proposés à celui de cette revue. Une recherche par nom borne la requête.
"""

from sqlalchemy import Connection

from infrastructure.read_models._common import EntityFacetResponse, EntityKind
from infrastructure.read_models.entity_facet import entity_facet_rows
from infrastructure.read_models.filters import own_structure_ids
from infrastructure.read_models.publications.filtering import (
    filter_context,
    publication_filter_where,
)
from infrastructure.read_models.publications.models import PublicationFilters

_LIMIT = 20


class StatsEntityFacetQueries:
    _conn: Connection

    def stats_entity_facet(
        self,
        *,
        kind: EntityKind,
        search: str,
        filters: PublicationFilters,
    ) -> EntityFacetResponse:
        context = filter_context(self._conn, filters)
        # Le filtre de la dimension demandée est écarté : une sélection ne réduit pas ses propres options.
        where, binds = publication_filter_where(filters, context, kind)
        return EntityFacetResponse(
            entities=entity_facet_rows(
                self._conn,
                kind=kind,
                where_sql=where,
                binds=binds,
                search=search,
                limit=_LIMIT,
                own_structure_ids=own_structure_ids(
                    filters.lab_ids, context.perimeter_structure_ids
                ),
            )
        )
