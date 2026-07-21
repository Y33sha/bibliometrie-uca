"""Helpers partagés par les agrégats stats : périmètre de base, assemblage des filtres, filtre APC."""

from typing import Any

from application.ports.api.stats_queries import StatsFilters
from infrastructure.queries.api.filters import (
    PUBLICATION_IS_IN_PERIMETER,
    WhereClause,
    doc_type_clause,
    lab_clause,
    oa_clause,
    year_clause,
)

# Périmètre commun aux agrégats stats : corpus in-perimeter, hors revues-dépôts (serveurs de
# preprint). Le type de document n'est PAS figé ici — c'est un filtre comme un autre (cf.
# `doc_type_clause`). Suppose une table `publications p` avec `LEFT JOIN journals j` dans la requête.
STATS_BASE = " AND ".join(
    [PUBLICATION_IS_IN_PERIMETER, "(j.oa_model IS DISTINCT FROM 'repository')"]
)


def stats_filter_clauses(
    *,
    perimeter_structure_ids: list[int],
    filters: StatsFilters,
) -> list[WhereClause | None]:
    """Clauses de filtrage communes aux agrégats stats (années, labos, accès, APC, types, éditeur,
    revue). À assembler avec `assemble_where`."""
    out: list[WhereClause | None] = [
        year_clause(filters.years),
        lab_clause(filters.lab_ids),
        oa_clause(filters.oa_status),
        stats_apc_clause(filters.has_apc, perimeter_structure_ids),
        doc_type_clause(filters.doc_types),
    ]
    if filters.publisher_ids:
        out.append(
            WhereClause(
                "j.publisher_id = ANY(:flt_publisher_ids)",
                {"flt_publisher_ids": filters.publisher_ids},
            )
        )
    if filters.journal_ids:
        out.append(
            WhereClause(
                "p.journal_id = ANY(:flt_journal_ids)", {"flt_journal_ids": filters.journal_ids}
            )
        )
    return out


# Fragments APC spécifiques aux agrégations stats, distincts d'`apc_clause`
# (`filters.py`), qui ne teste que l'existence d'un paiement.
_APC_EXISTS_SA = (
    "EXISTS (SELECT 1 FROM apc_payments ap "
    "WHERE ap.publication_id = p.id "
    "AND ap.budget_structure_id = ANY(CAST(:apc_root_ids AS int[])))"
)
_APC_NOT_EXISTS_SA = (
    "NOT EXISTS (SELECT 1 FROM apc_payments ap "
    "WHERE ap.publication_id = p.id "
    "AND ap.budget_structure_id = ANY(CAST(:apc_root_ids AS int[])))"
)


def stats_apc_clause(has_apc: list[str], perimeter_structure_ids: list[int]) -> WhereClause | None:
    """Filtre APC pour les endpoints stats (supporte multi-sélection).

    `perimeter_structure_ids` = les structures du périmètre `persons`, que l'adapter
    résout et qui tiennent lieu de structures « internes ».
    Toutes les valeurs APC partagent le bind `:apc_root_ids` ; la valeur
    est constante par requête.
    """
    if not has_apc:
        return None
    parts: list[str] = []
    needs_root = False
    for v in has_apc:
        if v == "uca":
            parts.append(_APC_EXISTS_SA)
            needs_root = True
        elif v == "non_uca":
            parts.append(
                f"(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) "
                f"AND {_APC_NOT_EXISTS_SA})"
            )
            needs_root = True
        elif v == "none":
            parts.append(
                "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)"
            )
    if not parts:
        return None
    binds: dict[str, Any] = {"apc_root_ids": perimeter_structure_ids} if needs_root else {}
    if len(parts) == 1:
        return WhereClause(parts[0], binds)
    return WhereClause("(" + " OR ".join(parts) + ")", binds)
