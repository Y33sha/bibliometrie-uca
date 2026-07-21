"""Facette d'entité contextuelle (éditeur, revue) pour le tableau de bord.

Renvoie les N premières entités par volume, calculées **sous les filtres actifs** (en sautant le
filtre de la dimension demandée, pour qu'une sélection ne réduise pas ses propres options). Les
autres filtres — dont l'autre entité — sont inclus : sélectionner une revue restreint donc les
éditeurs proposés à celui de cette revue. Une recherche par nom borne la requête.

Les filtres étant scalaires ou en `EXISTS` (aucune jointure démultipliante), `COUNT(*)` par groupe
égale le nombre de publications distinctes.
"""

from typing import Any, Literal

from sqlalchemy import Connection, text

from application.ports.api.stats_queries import StatsFilters
from infrastructure.queries.api.filters import (
    PUBLICATION_IS_IN_PERIMETER,
    WhereClause,
    assemble_where,
    doc_type_clause,
    lab_clause,
    oa_clause,
    year_clause,
)
from infrastructure.queries.api.stats._shared import stats_apc_clause

EntityKind = Literal["publisher", "journal"]

_BASE = " AND ".join([PUBLICATION_IS_IN_PERIMETER, "(j.oa_model IS DISTINCT FROM 'repository')"])

# Liaison SQL par entité : expression d'identifiant, de libellé et jointure additionnelle. La revue
# sort directement de `publications.journal_id` (colonne indexée) ; l'éditeur passe par une jointure
# un-à-un vers `publishers` (qui exclut les publications sans éditeur).
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
) -> list[dict[str, Any]]:
    # On saute le filtre de la dimension demandée (sinon une sélection réduit ses propres options).
    publisher_ids = [] if kind == "publisher" else filters.publisher_ids
    journal_ids = [] if kind == "journal" else filters.journal_ids

    clauses: list[WhereClause | None] = [
        year_clause(filters.years),
        lab_clause(filters.lab_ids),
        oa_clause(filters.oa_status),
        stats_apc_clause(filters.has_apc, perimeter_structure_ids),
        doc_type_clause(filters.doc_types),
    ]
    if publisher_ids:
        clauses.append(
            WhereClause(
                "j.publisher_id = ANY(:flt_publisher_ids)", {"flt_publisher_ids": publisher_ids}
            )
        )
    if journal_ids:
        clauses.append(
            WhereClause("p.journal_id = ANY(:flt_journal_ids)", {"flt_journal_ids": journal_ids})
        )
    where, binds = assemble_where(clauses)

    sp = _KIND_SQL[kind]
    name_filter = ""
    if len(search.strip()) >= 2:
        name_filter = f" AND unaccent({sp['label']}) ILIKE unaccent(:q)"
        binds["q"] = f"%{search.strip()}%"
    binds["lim"] = limit

    sql = f"""
        SELECT {sp["id"]} AS id, {sp["label"]} AS label, COUNT(*) AS count
        FROM publications p
        LEFT JOIN journals j ON j.id = p.journal_id {sp["join"]}
        WHERE {_BASE} AND {where} AND {sp["id"]} IS NOT NULL{name_filter}
        GROUP BY {sp["id"]}, {sp["label"]}
        ORDER BY count DESC, label
        LIMIT :lim
    """
    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(text(sql), binds).all()
    return [{"id": r.id, "label": r.label, "count": r.count} for r in rows]
