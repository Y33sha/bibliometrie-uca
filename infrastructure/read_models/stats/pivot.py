"""Moteur d'agrégation générique (pivot).

Liaison SQL du registre `domain.stats` + constructeur de requête sur **liste blanche** : la composition `SELECT <dimensions>, <mesure> … GROUP BY <dimensions>` n'utilise que des expressions connues, indexées par les clés validées du registre. Aucun SQL libre, aucune injection : le vocabulaire est borné côté domaine, l'infrastructure n'y associe que des fragments SQL.

Le grain est tenu par une sous-requête qui rend chaque publication une fois par groupe (`SELECT DISTINCT <dimensions>, p.id`). Une dimension qui démultiplie les lignes (`lab`) ne fait donc compter ni sommer deux fois la même publication.
"""

from sqlalchemy import Connection, text

from application.ports.read_models.publications_queries import NO_LICENSE
from application.ports.read_models.stats_queries import PivotResponse, StatsFilters
from domain.publications.doc_types import DOC_TYPE_FAMILIES
from domain.publications.metadata import OaStatus
from domain.stats import DIMENSIONS, MEASURES, Dimension, validate_pivot
from domain.structures.structure import StructureType
from infrastructure.read_models.filters import OA_OPEN_SQL, assemble_where
from infrastructure.read_models.stats._shared import STATS_BASE, stats_filter_clauses


def doc_type_grouped_sql(column: str = "p.doc_type") -> str:
    """Expression SQL `CASE` projetant `column` (enum `doc_type`) sur la clé de groupement du pivot : les types de la famille « publications » (article, communication, chapitre…) gardent leur grain fin, les autres familles restent agrégées sous leur clé de famille. Le détail là où il porte le plus d'information (les publications au sens strict, dont la répartition varie fortement d'un laboratoire à l'autre), le grossier ailleurs. Couvre exhaustivement l'enum ; les types non listés tombent dans `misc` (filet)."""
    expanded = DOC_TYPE_FAMILIES["publications"]
    whens = [
        f"WHEN {column}::text IN ({', '.join(f'{t.value!r}' for t in expanded)}) THEN {column}::text"
    ]
    whens += [
        f"WHEN {column}::text IN ({', '.join(f'{t.value!r}' for t in types)}) THEN {family!r}"
        for family, types in DOC_TYPE_FAMILIES.items()
        if family != "publications"
    ]
    return f"CASE {' '.join(whens)} ELSE 'misc' END"


# Liaison SQL par clé de dimension : expression de groupement et jointure éventuelle.
_DIM_EXPR: dict[str, str] = {
    "year": "p.pub_year",
    "oa_access": (
        f"CASE WHEN p.oa_status::text IN {OA_OPEN_SQL} THEN 'ouvert' "
        f"WHEN p.oa_status = '{OaStatus.EMBARGOED.value}' THEN 'embargo' "
        f"WHEN p.oa_status = '{OaStatus.CLOSED.value}' THEN 'ferme' "
        "ELSE 'indetermine' END"
    ),
    "oa_voie": "p.oa_status::text",
    "doc_type_grouped": doc_type_grouped_sql("p.doc_type"),
    "lab": "COALESCE(ls.acronym, ls.name)",
    "publisher": "pub.name",
    "journal": "jt.title",
    "license": f"COALESCE(p.license::text, '{NO_LICENSE}')",
}
# Jointures par dimension hors `publications`. Le laboratoire passe par `publication_structures` (une publication compte dans chacun des labos de ses auteurs). Alias dédiés (`lps`/`ls`), distincts de la sous-requête de `lab_clause`.
_DIM_JOIN: dict[str, str] = {
    "lab": (
        "JOIN publication_structures lps ON lps.publication_id = p.id "
        f"JOIN structures ls ON ls.id = lps.structure_id AND ls.structure_type = '{StructureType.LABO.value}'"
    ),
    # Éditeur / revue : jointures internes (excluent les publications sans revue / sans éditeur).
    "publisher": "JOIN publishers pub ON pub.id = j.publisher_id",
    "journal": "JOIN journals jt ON jt.id = p.journal_id",
}
# Agrégat de chaque mesure sur les publications distinctes `g`, et jointure éventuelle.
_MEASURE_AGG: dict[str, str] = {
    "pub_count": "COUNT(*)",
    "apc_amount": "COALESCE(SUM(apc.amount), 0)::float8",
}
_MEASURE_JOIN: dict[str, str] = {
    "apc_amount": (
        "LEFT JOIN (SELECT ap.publication_id, SUM(ap.amount_eur_ht) AS amount "
        "FROM apc_payments ap "
        "WHERE ap.budget_structure_id = ANY(CAST(:measure_apc_root_ids AS int[])) "
        "GROUP BY ap.publication_id) apc ON apc.publication_id = g.publication_id"
    ),
}

# Garde-fou d'extensibilité : toute dimension *groupable* a sa liaison SQL de groupement, et réciproquement ; idem pour les mesures. Les dimensions filtrables-seules (APC, labo) n'ont pas de groupement — leur filtrage vit dans `filters.py`.
_GROUPABLE = {key for key, dim in DIMENSIONS.items() if dim.groupable}
assert set(_DIM_EXPR) == _GROUPABLE, "liaison SQL des dimensions désynchronisée du registre"
assert set(_MEASURE_AGG) == set(MEASURES), "liaison SQL des mesures désynchronisée du registre"


def _order_by(dims: list[Dimension]) -> str:
    """Dimensions ordinales d'abord (ASC, lecture chronologique), puis par la mesure décroissante."""
    parts = [d.key for d in dims if d.ordinal]
    parts.append("value DESC NULLS LAST")
    return ", ".join(parts)


def run_pivot(
    conn: Connection,
    *,
    measure: str,
    groups: list[str],
    perimeter_structure_ids: list[int],
    filters: StatsFilters,
) -> PivotResponse:
    """Exécute une agrégation : `mesure` ventilée selon `groups`, sous les filtres. Les clés sont validées contre le registre (`validate_pivot`) avant toute composition SQL."""
    m, dims = validate_pivot(measure, groups)
    where, binds = assemble_where(
        stats_filter_clauses(
            perimeter_structure_ids=perimeter_structure_ids,
            filters=filters,
        )
    )
    joins = " ".join(dict.fromkeys(_DIM_JOIN[d.key] for d in dims if d.key in _DIM_JOIN))
    inner_select = ", ".join(
        [*[f"{_DIM_EXPR[d.key]} AS {d.key}" for d in dims], "p.id AS publication_id"]
    )
    inner = (
        f"SELECT DISTINCT {inner_select} FROM publications p "
        f"LEFT JOIN journals j ON j.id = p.journal_id {joins} "
        f"WHERE {STATS_BASE} AND {where}"
    )
    keys = [d.key for d in dims]
    select = ", ".join([*keys, f"{_MEASURE_AGG[m.key]} AS value"])
    sql = f"SELECT {select} FROM ({inner}) g {_MEASURE_JOIN.get(m.key, '')}"
    if dims:
        sql += f" GROUP BY {', '.join(keys)} ORDER BY {_order_by(dims)}"

    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(text(sql), {**binds, "measure_apc_root_ids": perimeter_structure_ids}).all()
    return PivotResponse(
        measure=m.key,
        groups=[d.key for d in dims],
        rows=[dict(r._mapping) for r in rows],
    )
