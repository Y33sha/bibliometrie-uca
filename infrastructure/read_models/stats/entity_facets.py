"""Facette d'entité contextuelle (éditeur, revue) pour le tableau de bord.

Renvoie les N premières entités par volume, calculées **sous les filtres actifs** (en sautant le filtre de la dimension demandée, pour qu'une sélection ne réduise pas ses propres options). Les autres filtres — dont l'autre entité — sont inclus : sélectionner une revue restreint donc les éditeurs proposés à celui de cette revue. Une recherche par nom borne la requête.

Les filtres étant scalaires ou en `EXISTS` (aucune jointure démultipliante), `COUNT(*)` par groupe égale le nombre de publications distinctes.
"""

from dataclasses import replace
from typing import Literal

from sqlalchemy import Connection, text

from application.ports.read_models._common import EntityFacetItem
from application.ports.read_models.stats_queries import StatsFilters
from infrastructure.read_models.filters import assemble_where
from infrastructure.read_models.stats._shared import STATS_BASE, stats_filter_clauses

EntityKind = Literal["publisher", "journal"]

# Liaison SQL par entité : identifiant, libellé, jointure additionnelle. La revue sort de `publications.journal_id` ; l'éditeur passe par une jointure un-à-un vers `publishers` (qui exclut les publications sans éditeur).
_KIND_SQL: dict[str, dict[str, str]] = {
    "journal": {"id": "j.id", "label": "j.title", "join": ""},
    "publisher": {
        "id": "pub.id",
        "label": "pub.name",
        "join": "JOIN publishers pub ON pub.id = j.publisher_id",
    },
}


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

    sp = _KIND_SQL[kind]
    name_filter = ""
    if len(search.strip()) >= 2:
        name_filter = f" AND unaccent({sp['label']}) ILIKE unaccent(:q)"
        binds["q"] = f"%{search.strip()}%"
    binds["lim"] = limit

    sql = f"""
        SELECT {sp["id"]} AS id, {sp["label"]} AS label, COUNT(*) AS n
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id {sp["join"]}
        WHERE {STATS_BASE} AND {where} AND {sp["id"]} IS NOT NULL{name_filter}
        GROUP BY {sp["id"]}, {sp["label"]}
        ORDER BY n DESC, label
        LIMIT :lim
    """
    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(text(sql), binds).all()
    return [EntityFacetItem(id=r.id, label=r.label, count=r.n) for r in rows]
