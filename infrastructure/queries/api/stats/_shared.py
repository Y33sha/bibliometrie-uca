"""Helpers partagés par les agrégats stats : périmètre de base, assemblage des filtres, filtre APC."""

from typing import Any

from infrastructure.queries.filters import (
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
    apc_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
    publisher_ids: list[int],
    journal_ids: list[int],
    oa_status: str,
    has_apc: str,
    doc_types: list[str],
) -> list[WhereClause | None]:
    """Clauses de filtrage communes aux agrégats stats (années, labos, accès, APC, types, éditeur,
    revue). À assembler avec `assemble_where`."""
    out: list[WhereClause | None] = [
        year_clause(years),
        lab_clause(lab_ids),
        oa_clause(oa_status),
        stats_apc_clause(has_apc, apc_structure_ids),
        doc_type_clause(doc_types),
    ]
    if publisher_ids:
        out.append(
            WhereClause(
                "j.publisher_id = ANY(:flt_publisher_ids)", {"flt_publisher_ids": publisher_ids}
            )
        )
    if journal_ids:
        out.append(
            WhereClause("p.journal_id = ANY(:flt_journal_ids)", {"flt_journal_ids": journal_ids})
        )
    return out


# Fragments APC — définis ici car spécifiques aux agrégations stats
# (distincts de `apc_clause` de filters.py qui filtre sur l'existence).
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


def stats_apc_clause(has_apc: str, apc_structure_ids: list[int]) -> WhereClause | None:
    """Filtre APC pour les endpoints stats (supporte multi-sélection).

    `apc_structure_ids` = structures considérées comme "internes" pour la
    catégorisation APC (typiquement le périmètre `perimeter_persons`).
    Toutes les valeurs APC partagent le bind `:apc_root_ids` ; la valeur
    est constante par requête.
    """
    if not has_apc:
        return None
    values = [v.strip() for v in has_apc.split(",") if v.strip()]
    parts: list[str] = []
    needs_root = False
    for v in values:
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
    binds: dict[str, Any] = {"apc_root_ids": apc_structure_ids} if needs_root else {}
    if len(parts) == 1:
        return WhereClause(parts[0], binds)
    return WhereClause("(" + " OR ".join(parts) + ")", binds)
