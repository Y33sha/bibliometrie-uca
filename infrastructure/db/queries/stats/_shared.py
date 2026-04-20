"""Helpers partagés : filtre APC et pagination pour les endpoints stats."""

from typing import Any

# Fragments APC — définis ici car spécifiques aux agrégations stats
# (distincts de apply_apc_filter qui filtre sur l'existence).
_APC_EXISTS = (
    "EXISTS (SELECT 1 FROM apc_payments ap "
    "WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s)"
)
_APC_NOT_EXISTS = (
    "NOT EXISTS (SELECT 1 FROM apc_payments ap "
    "WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s)"
)
APC_SUM = """COALESCE((SELECT SUM(ap.amount_eur_ht)
     FROM apc_payments ap
     WHERE ap.publication_id = p.id AND ap.budget_structure_id = %s
    ), 0)"""

_APC_FILTER_MAP = {
    "uca": (_APC_EXISTS, 1),
    "non_uca": (
        f"(EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id) "
        f"AND {_APC_NOT_EXISTS})",
        1,
    ),
    "none": (
        "NOT EXISTS (SELECT 1 FROM apc_payments ap WHERE ap.publication_id = p.id)",
        0,
    ),
}


def apply_stats_apc_filter(
    conditions: list, params: list, has_apc: str, root_structure_id: int
) -> None:
    """Filtre APC spécifique aux endpoints stats (supporte multi-sélection)."""
    if not has_apc:
        return
    values = [v.strip() for v in has_apc.split(",") if v.strip()]
    entries = [_APC_FILTER_MAP[v] for v in values if v in _APC_FILTER_MAP]
    parts = [e[0] for e in entries]
    for e in entries:
        params.extend([root_structure_id] * e[1])
    if len(parts) == 1:
        conditions.append(parts[0])
    elif len(parts) > 1:
        conditions.append("(" + " OR ".join(parts) + ")")


def paginated(total: int, page: int, per_page: int, key: str, rows: list) -> dict[str, Any]:
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        key: rows,
    }
