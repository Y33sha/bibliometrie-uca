"""Agrégat des collaborations internationales par pays.

Compte, pour chaque pays étranger, le nombre de publications du périmètre qui lui sont
co-affiliées, en dépliant la colonne `publications.countries` (ensemble des pays présents dans les
affiliations d'une publication). Le pays de rattachement du périmètre est exclu : l'indicateur mesure
l'ouverture *internationale*, pas la présence domestique (quasi universelle).

Réutilise le périmètre de base et les filtres communs des agrégats stats (cf. `_shared`).
"""

from typing import Any

from sqlalchemy import Connection, text

from infrastructure.queries.api.stats._shared import STATS_BASE, stats_filter_clauses
from infrastructure.queries.filters import assemble_where

# Pays de rattachement du périmètre (France), exclu du décompte des collaborations internationales.
# Codes pays en ISO 3166-1 alpha-2 minuscule, comme stockés dans `publications.countries`.
_DOMESTIC_COUNTRY = "fr"


def run_collaborations(
    conn: Connection,
    *,
    apc_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
    publisher_ids: list[int],
    journal_ids: list[int],
    oa_status: str,
    has_apc: str,
    doc_types: list[str],
) -> dict[str, Any]:
    """Nombre de publications co-affiliées à chaque pays étranger, sous les filtres. Retourne des
    lignes `{code, value}` triées par décompte décroissant."""
    where, binds = assemble_where(
        stats_filter_clauses(
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_ids=publisher_ids,
            journal_ids=journal_ids,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
        )
    )
    binds["domestic_country"] = _DOMESTIC_COUNTRY
    sql = (
        "SELECT country AS code, COUNT(DISTINCT p.id) AS value "
        "FROM publications p "
        "LEFT JOIN journals j ON j.id = p.journal_id "
        "CROSS JOIN LATERAL unnest(p.countries) AS country "
        f"WHERE {STATS_BASE} AND {where} AND country <> :domestic_country "
        "GROUP BY country ORDER BY value DESC"
    )
    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(text(sql), binds).all()
    return {"rows": [dict(r._mapping) for r in rows]}
