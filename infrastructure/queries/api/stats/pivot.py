"""Moteur d'agrégation générique (pivot).

Liaison SQL du registre `domain.stats` + constructeur de requête sur **liste blanche** :
la composition `SELECT <dimensions>, <mesure> … GROUP BY <dimensions>` n'utilise que des
expressions connues, indexées par les clés validées du registre. Aucun SQL libre, aucune
injection : le vocabulaire est borné côté domaine, l'infrastructure n'y associe que des
fragments SQL.

Le grain est tenu par les mesures : toutes comptent les publications de façon distincte
(`COUNT(DISTINCT p.id)`), si bien qu'une dimension qui démultiplie (`lab`) ne les surcompte pas.
"""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.stats_queries import StatsFilters
from domain.publications.doc_types import DOC_TYPE_FAMILIES
from domain.stats import DIMENSIONS, MEASURES, Dimension, validate_pivot
from infrastructure.queries.api.stats._shared import STATS_BASE, stats_filter_clauses
from infrastructure.queries.filters import OA_OPEN_SQL, assemble_where


def doc_type_grouped_sql(column: str = "p.doc_type") -> str:
    """Expression SQL `CASE` projetant `column` (enum `doc_type`) sur la clé de groupement du pivot : les types de la famille « publications » (article, communication, chapitre…) gardent leur grain fin, les autres familles restent agrégées sous leur clé de famille. Le détail là où il porte le plus d'information (les publications au sens strict, dont la répartition varie fortement d'un laboratoire à l'autre), le grossier ailleurs. Couvre exhaustivement l'enum ; les types non listés tombent dans `misc` (filet)."""
    expanded = DOC_TYPE_FAMILIES["publications"]
    whens = [
        f"WHEN {column}::text IN ({', '.join(f'{t!r}' for t in expanded)}) THEN {column}::text"
    ]
    whens += [
        f"WHEN {column}::text IN ({', '.join(f'{t!r}' for t in types)}) THEN {family!r}"
        for family, types in DOC_TYPE_FAMILIES.items()
        if family != "publications"
    ]
    return f"CASE {' '.join(whens)} ELSE 'misc' END"


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
    "doc_type_grouped": doc_type_grouped_sql("p.doc_type"),
    "lab": "COALESCE(ls.acronym, ls.name)",
    "publisher": "pub.name",
    "journal": "jt.title",
}
# Jointures supplémentaires par dimension qui sort de `publications`. Le laboratoire passe par les
# rattachements (une publication compte dans chacun de ses laboratoires). Alias dédiés (`la`/`las`/
# `ls`) pour ne pas heurter la sous-requête de `lab_clause`.
_DIM_JOIN: dict[str, str] = {
    "lab": (
        "JOIN authorships la ON la.publication_id = p.id "
        "JOIN authorship_structures las ON las.authorship_id = la.id "
        "JOIN structures ls ON ls.id = las.structure_id AND ls.structure_type = 'labo'"
    ),
    # Éditeur / revue : jointures internes (excluent les publications sans revue / sans éditeur).
    "publisher": "JOIN publishers pub ON pub.id = j.publisher_id",
    "journal": "JOIN journals jt ON jt.id = p.journal_id",
}
_MEASURE_AGG: dict[str, str] = {
    "pub_count": "COUNT(DISTINCT p.id)",
}

# Garde-fou d'extensibilité : toute dimension *groupable* a sa liaison SQL de groupement, et
# réciproquement ; idem pour les mesures. Les dimensions filtrables-seules (APC, labo) n'ont pas
# d'expression de groupement — leur SQL de filtrage vit dans les clauses de `filters.py`.
_GROUPABLE = {key for key, dim in DIMENSIONS.items() if dim.groupable}
assert set(_DIM_EXPR) == _GROUPABLE, "liaison SQL des dimensions désynchronisée du registre"
assert set(_MEASURE_AGG) == set(MEASURES), "liaison SQL des mesures désynchronisée du registre"


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
    perimeter_structure_ids: list[int],
    filters: StatsFilters,
) -> dict[str, Any]:
    """Exécute une agrégation : `mesure` ventilée selon `groups`, sous les filtres. Les clés sont
    validées contre le registre (`validate_pivot`) avant toute composition SQL."""
    m, dims = validate_pivot(measure, groups)
    where, binds = assemble_where(
        stats_filter_clauses(
            perimeter_structure_ids=perimeter_structure_ids,
            filters=filters,
        )
    )
    joins = " ".join(dict.fromkeys(_DIM_JOIN[d.key] for d in dims if d.key in _DIM_JOIN))
    select = ", ".join(
        [*[f"{_DIM_EXPR[d.key]} AS {d.key}" for d in dims], f"{_MEASURE_AGG[m.key]} AS value"]
    )
    sql = (
        f"SELECT {select} FROM publications p "
        f"LEFT JOIN journals j ON j.id = p.journal_id {joins} "
        f"WHERE {STATS_BASE} AND {where}"
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
