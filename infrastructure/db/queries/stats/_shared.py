"""Helpers partagés : filtre APC et pagination pour les endpoints stats."""

from typing import Any

from infrastructure.db.queries.filters import WhereClause

# Fragments APC — définis ici car spécifiques aux agrégations stats
# (distincts de `apc_clause` de filters.py qui filtre sur l'existence).
APC_SUM_SA = """COALESCE((SELECT SUM(ap.amount_eur_ht)
     FROM apc_payments ap
     WHERE ap.publication_id = p.id AND ap.budget_structure_id = :apc_root
    ), 0)"""

_APC_EXISTS_SA = (
    "EXISTS (SELECT 1 FROM apc_payments ap "
    "WHERE ap.publication_id = p.id AND ap.budget_structure_id = :apc_root)"
)
_APC_NOT_EXISTS_SA = (
    "NOT EXISTS (SELECT 1 FROM apc_payments ap "
    "WHERE ap.publication_id = p.id AND ap.budget_structure_id = :apc_root)"
)


def stats_apc_clause(has_apc: str, root_structure_id: int) -> WhereClause | None:
    """Filtre APC pour les endpoints stats (supporte multi-sélection).

    Toutes les valeurs APC qui référencent `root_structure_id` partagent
    le même bind `:apc_root` ; la valeur est constante par requête.
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
    binds: dict[str, Any] = {"apc_root": root_structure_id} if needs_root else {}
    if len(parts) == 1:
        return WhereClause(parts[0], binds)
    return WhereClause("(" + " OR ".join(parts) + ")", binds)


def paginated(total: int, page: int, per_page: int, key: str, rows: list) -> dict[str, Any]:
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        key: rows,
    }
