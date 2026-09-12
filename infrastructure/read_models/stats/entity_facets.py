"""Facette d'entité contextuelle (éditeur, revue) pour le tableau de bord.

Renvoie les N premières entités par volume, calculées **sous les filtres actifs** (en sautant le filtre de la dimension demandée, pour qu'une sélection ne réduise pas ses propres options). Les autres filtres — dont l'autre entité — sont inclus : sélectionner une revue restreint donc les éditeurs proposés à celui de cette revue. Une recherche par nom borne la requête.
"""

from dataclasses import replace

from sqlalchemy import Connection

from application.ports.read_models._common import EntityFacetItem, EntityKind
from application.ports.read_models.stats_queries import StatsFilters
from infrastructure.read_models.entity_facet import entity_facet_rows
from infrastructure.read_models.filters import assemble_where
from infrastructure.read_models.stats._shared import STATS_BASE, stats_filter_clauses


def stats_entity_facet(
    conn: Connection,
    *,
    kind: EntityKind,
    search: str,
    perimeter_structure_ids: list[int],
    filters: StatsFilters,
    limit: int = 20,
) -> list[EntityFacetItem]:
    # On saute le filtre de la dimension demandée (sinon une sélection réduit ses propres options).
    filters_for_facet = replace(
        filters,
        publisher_ids=[] if kind == "publisher" else filters.publisher_ids,
        journal_ids=[] if kind == "journal" else filters.journal_ids,
    )
    where, binds = assemble_where(
        stats_filter_clauses(
            perimeter_structure_ids=perimeter_structure_ids, filters=filters_for_facet
        )
    )
    return entity_facet_rows(
        conn,
        kind=kind,
        where_sql=f"{STATS_BASE} AND {where}",
        binds=binds,
        search=search,
        limit=limit,
    )
