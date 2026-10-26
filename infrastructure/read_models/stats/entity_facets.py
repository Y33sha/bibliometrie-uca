"""Facette d'entité contextuelle (éditeur, revue, organisation partenaire) pour le tableau de bord.

Renvoie les N premières entités par volume, calculées **sous les filtres actifs** (en sautant le filtre de la dimension demandée, pour qu'une sélection ne réduise pas ses propres options). Les autres filtres — dont l'autre entité — sont inclus : sélectionner une revue restreint donc les éditeurs proposés à celui de cette revue. Une recherche par nom borne la requête.
"""

from dataclasses import replace

from sqlalchemy import Connection

from infrastructure.read_models._common import EntityFacetResponse, EntityKind
from infrastructure.read_models.entity_facet import entity_facet_rows
from infrastructure.read_models.filters import assemble_where, own_structure_ids
from infrastructure.read_models.perimeters.queries import get_persons_structure_ids_list
from infrastructure.read_models.stats._shared import STATS_BASE, stats_filter_clauses
from infrastructure.read_models.stats.models import StatsFilters

_LIMIT = 20


class StatsEntityFacetQueries:
    _conn: Connection

    def stats_entity_facet(
        self,
        *,
        kind: EntityKind,
        search: str,
        filters: StatsFilters,
    ) -> EntityFacetResponse:
        perimeter_structure_ids = get_persons_structure_ids_list(self._conn)
        # On saute le filtre de la dimension demandée (sinon une sélection réduit ses propres options).
        filters_for_facet = replace(
            filters,
            publisher_ids=[] if kind == "publisher" else filters.publisher_ids,
            serial_ids=[] if kind == "serial" else filters.serial_ids,
            partner_rors=[] if kind == "partner" else filters.partner_rors,
        )
        where, binds = assemble_where(
            stats_filter_clauses(
                perimeter_structure_ids=perimeter_structure_ids, filters=filters_for_facet
            )
        )
        return EntityFacetResponse(
            entities=entity_facet_rows(
                self._conn,
                kind=kind,
                where_sql=f"{STATS_BASE} AND {where}",
                binds=binds,
                search=search,
                limit=_LIMIT,
                own_structure_ids=own_structure_ids(filters.lab_ids, perimeter_structure_ids),
            )
        )
