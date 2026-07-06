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
    oa_status: list[str],
    has_apc: list[str],
    doc_types: list[str],
) -> dict[str, Any]:
    """Collaborations internationales sous les filtres. Retourne les lignes `{code, value}` (un pays
    étranger, nombre de publications co-affiliées) triées par décompte décroissant, ainsi que le
    nombre de publications en collaboration internationale (au moins un pays étranger) et le total du
    corpus filtré — de quoi exprimer une part."""
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
    conn.execute(text("SET LOCAL jit = off"))

    per_country = (
        "SELECT country AS code, COUNT(DISTINCT p.id) AS value "
        "FROM publications p "
        "LEFT JOIN journals j ON j.id = p.journal_id "
        "CROSS JOIN LATERAL unnest(p.countries) AS country "
        f"WHERE {STATS_BASE} AND {where} AND country <> :domestic_country "
        "GROUP BY country ORDER BY value DESC"
    )
    rows = conn.execute(text(per_country), binds).all()

    # Numérateur (publications avec au moins un pays étranger) et dénominateur (corpus filtré), au grain
    # publication : `array_remove` retire le pays domestique ; un reste non vide signale l'international.
    totals = (
        "SELECT COUNT(DISTINCT p.id) AS total, "
        "COUNT(DISTINCT p.id) FILTER "
        "(WHERE cardinality(array_remove(p.countries, :domestic_country)) > 0) AS international "
        "FROM publications p "
        "LEFT JOIN journals j ON j.id = p.journal_id "
        f"WHERE {STATS_BASE} AND {where}"
    )
    agg = conn.execute(text(totals), binds).one()

    return {
        "rows": [dict(r._mapping) for r in rows],
        "international_count": agg.international or 0,
        "total_count": agg.total or 0,
    }
