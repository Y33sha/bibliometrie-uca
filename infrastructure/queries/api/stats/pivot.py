"""Moteur d'agrégation générique (pivot).

Liaison SQL du registre `domain.stats.pivot` + constructeur de requête sur **liste blanche** :
la composition `SELECT <dimensions>, <mesure> … GROUP BY <dimensions>` n'utilise que des
expressions connues, indexées par les clés validées du registre. Aucun SQL libre, aucune
injection : le vocabulaire est borné côté domaine, l'infrastructure n'y associe que des
fragments SQL.

Le grain est tenu par les mesures : toutes comptent les publications de façon distincte
(`COUNT(DISTINCT p.id)`), donc une dimension qui démultiplie (`source`) ne surcompte pas.
"""

from typing import Any

from sqlalchemy import Connection, text

from domain.stats.pivot import DIMENSIONS, MEASURES, Dimension, validate_pivot
from infrastructure.queries.api.stats._shared import stats_apc_clause
from infrastructure.queries.filters import (
    OA_OPEN_SQL,
    PUBLICATION_IS_IN_PERIMETER,
    WhereClause,
    assemble_where,
    doc_type_clause,
    lab_clause,
    oa_clause,
    year_clause,
)

# Liaison SQL par clé de dimension : expression de groupement et jointure éventuelle.
_DIM_EXPR: dict[str, str] = {
    "year": "p.pub_year",
    "oa_access": (
        f"CASE WHEN p.oa_status::text IN {OA_OPEN_SQL} THEN 'ouvert' "
        "WHEN p.oa_status = 'embargoed' THEN 'embargo' "
        "WHEN p.oa_status = 'closed' THEN 'ferme' "
        "ELSE 'indetermine' END"
    ),
    "oa_voie": "p.oa_status::text",
    "doc_type": "p.doc_type::text",
    "source": "src.source::text",
}
_DIM_JOIN: dict[str, str] = {
    "source": "CROSS JOIN unnest(p.sources) AS src(source)",
}
_MEASURE_AGG: dict[str, str] = {
    "pub_count": "COUNT(DISTINCT p.id)",
    "pct_open": (
        f"ROUND(COUNT(DISTINCT p.id) FILTER (WHERE p.oa_status::text IN {OA_OPEN_SQL}) "
        "* 100.0 / NULLIF(COUNT(DISTINCT p.id), 0), 1)"
    ),
}

# Garde-fou d'extensibilité : toute clé du registre domaine a sa liaison SQL, et réciproquement.
assert set(_DIM_EXPR) == set(DIMENSIONS), "liaison SQL des dimensions désynchronisée du registre"
assert set(_MEASURE_AGG) == set(MEASURES), "liaison SQL des mesures désynchronisée du registre"

# Périmètre du moteur : corpus in-perimeter, hors revues-dépôts (serveurs de preprint). Le type de
# document n'est PAS figé ici — c'est un filtre comme un autre (cf. `doc_type_clause`).
_BASE = " AND ".join([PUBLICATION_IS_IN_PERIMETER, "(j.oa_model IS DISTINCT FROM 'repository')"])


def _filter_clauses(
    *,
    apc_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
    doc_types: list[str],
) -> list[WhereClause | None]:
    out: list[WhereClause | None] = [
        year_clause(years),
        lab_clause(lab_ids),
        oa_clause(oa_status),
        stats_apc_clause(has_apc, apc_structure_ids),
        doc_type_clause(doc_types),
    ]
    if publisher_id:
        out.append(
            WhereClause("j.publisher_id = :flt_publisher_id", {"flt_publisher_id": publisher_id})
        )
    if journal_id:
        out.append(WhereClause("p.journal_id = :flt_journal_id", {"flt_journal_id": journal_id}))
    return out


def _order_by(dims: list[Dimension]) -> str:
    """Dimensions ordinales d'abord (ASC, lecture chronologique), puis par la mesure décroissante."""
    parts = [_DIM_EXPR[d.key] for d in dims if d.ordinal]
    parts.append("value DESC NULLS LAST")
    return ", ".join(parts)


def run_pivot(
    conn: Connection,
    *,
    measure: str,
    groups: list[str],
    apc_structure_ids: list[int],
    lab_ids: list[int],
    years: list[int],
    publisher_id: int | None,
    journal_id: int | None,
    oa_status: str,
    has_apc: str,
    doc_types: list[str],
) -> dict[str, Any]:
    """Exécute une agrégation : `mesure` ventilée selon `groups`, sous les filtres. Les clés sont
    validées contre le registre (`validate_pivot`) avant toute composition SQL."""
    m, dims = validate_pivot(measure, groups)
    where, binds = assemble_where(
        _filter_clauses(
            apc_structure_ids=apc_structure_ids,
            lab_ids=lab_ids,
            years=years,
            publisher_id=publisher_id,
            journal_id=journal_id,
            oa_status=oa_status,
            has_apc=has_apc,
            doc_types=doc_types,
        )
    )
    joins = " ".join(dict.fromkeys(_DIM_JOIN[d.key] for d in dims if d.key in _DIM_JOIN))
    select = ", ".join(
        [*[f"{_DIM_EXPR[d.key]} AS {d.key}" for d in dims], f"{_MEASURE_AGG[m.key]} AS value"]
    )
    sql = (
        f"SELECT {select} FROM publications p "
        f"LEFT JOIN journals j ON j.id = p.journal_id {joins} "
        f"WHERE {_BASE} AND {where}"
    )
    if dims:
        group_by = ", ".join(_DIM_EXPR[d.key] for d in dims)
        sql += f" GROUP BY {group_by} ORDER BY {_order_by(dims)}"

    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(text(sql), binds).all()
    return {
        "measure": m.key,
        "groups": [d.key for d in dims],
        "rows": [dict(r._mapping) for r in rows],
    }
