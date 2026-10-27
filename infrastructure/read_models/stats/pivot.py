"""Moteur d'agrégation générique (pivot) : registre des dimensions et des mesures, et constructeur de requête.

Une vue est une **mesure** agrégée selon un ou plusieurs **groupements**, sous des filtres. Le registre décrit chaque dimension et chaque mesure, avec sa liaison SQL. Ajouter une dimension ou une mesure = une entrée du registre.

Propriétés d'une dimension :
- **cardinalité** — `low` (peu de valeurs, portables sur un axe) ou `high` (milliers de valeurs : table classée ou top-N).
- **ordinal** — axe ordonné (l'année) ou catégoriel, qui change le tri et l'éligibilité au filtrage par plage.
- **groupable / comparable / filterable** — rôles : catégorie de ventilation, axe de comparaison (abscisse), facette. Une dimension groupable a une expression de groupement. Un axe comparable est toujours groupable.

Une mesure s'agrège sur les publications distinctes de chaque groupe : leur nombre, ou le montant des APC que l'établissement a payées pour elles. Le taux d'open access relève de la présentation.

Un **indicateur** est ce que l'interface propose d'afficher : une mesure, ventilée par une dimension empilée dans chaque barre. L'indicateur impose sa mesure. Un axe de comparaison facultatif s'ajoute à la ventilation (`indicator_pivot`).

La requête est composée sur **liste blanche** : `SELECT <dimensions>, <mesure> … GROUP BY <dimensions>` utilise seulement les expressions du registre, indexées par des clés validées (`validate_pivot`). Le grain est tenu par une sous-requête qui rend chaque publication une fois par groupe (`SELECT DISTINCT <dimensions>, p.id`). Une dimension qui démultiplie les lignes (`lab`) ne fait donc compter ni sommer deux fois la même publication.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

from domain.errors import ValidationError
from domain.publications.doc_types import DOC_TYPE_FAMILIES
from domain.publications.metadata import OaStatus
from domain.structures.structure import StructureType
from infrastructure.read_models.filters import (
    OA_OPEN_SQL,
    OWN_RORS_SQL,
    own_structure_ids,
)
from infrastructure.read_models.publications.filtering import (
    filter_context,
    publication_filter_where,
)
from infrastructure.read_models.publications.models import NO_LICENSE, PublicationFilters
from infrastructure.read_models.stats.models import (
    PivotDimensionOut,
    PivotIndicatorOut,
    PivotResponse,
    PivotSchemaResponse,
)

Cardinality = Literal["low", "high"]


@dataclass(frozen=True, slots=True)
class Dimension:
    """Un attribut d'une publication et ses rôles possibles :

    - groupable : catégorie de ventilation (empilée dans chaque barre), quand `group_sql` est renseigné ;
    - `comparable` : axe de comparaison (l'abscisse : l'année, les laboratoires, les éditeurs, les revues). L'accès et la voie d'accès se groupent mais ne se comparent pas ;
    - `filterable` : facette. Certaines dimensions sont seulement filtrables (APC : utile en filtre, sans intérêt comme axe). Leur filtrage vit dans `filters.py`.

    `group_sql` est l'expression de groupement sur la publication `p` et la revue `j`. `join_sql` est la jointure qu'elle demande.
    """

    key: str
    label: str
    cardinality: Cardinality
    ordinal: bool
    comparable: bool
    filterable: bool
    group_sql: str | None = None
    join_sql: str = ""

    @property
    def groupable(self) -> bool:
        return self.group_sql is not None


@dataclass(frozen=True, slots=True)
class Measure:
    """Une grandeur agrégée sur les publications distinctes `g` d'un groupe. `unit` est l'unité affichée, vide pour un nombre de publications. `agg_sql` est l'agrégat, `join_sql` la jointure qu'il demande."""

    key: str
    label: str
    agg_sql: str
    join_sql: str = ""
    unit: str = ""


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


DIMENSIONS: dict[str, Dimension] = {
    d.key: d
    for d in (
        Dimension(
            "year",
            "Année",
            "low",
            ordinal=True,
            comparable=True,
            filterable=True,
            group_sql="p.publication_year",
        ),
        Dimension(
            "oa_access",
            "Open access",
            "low",
            ordinal=False,
            comparable=False,
            filterable=False,
            group_sql=(
                f"CASE WHEN p.oa_status::text IN {OA_OPEN_SQL} THEN 'ouvert' "
                f"WHEN p.oa_status = '{OaStatus.EMBARGOED.value}' THEN 'embargo' "
                f"WHEN p.oa_status = '{OaStatus.CLOSED.value}' THEN 'ferme' "
                "ELSE 'indetermine' END"
            ),
        ),
        Dimension(
            "oa_voie",
            "Modèle OA",
            "low",
            ordinal=False,
            comparable=False,
            filterable=True,
            group_sql="p.oa_status::text",
        ),
        Dimension(
            "doc_type", "Type de document", "low", ordinal=False, comparable=False, filterable=True
        ),
        Dimension(
            "doc_type_grouped",
            "Productions",
            "low",
            ordinal=False,
            comparable=False,
            filterable=False,
            group_sql=doc_type_grouped_sql("p.doc_type"),
        ),
        # Forte cardinalité : comparaison paginée, pas de groupement primaire. Une publication compte dans chacun des labos de ses auteurs. Alias dédiés (`lps`/`ls`), distincts de la sous-requête de `lab_clause`.
        Dimension(
            "lab",
            "Laboratoire",
            "high",
            ordinal=False,
            comparable=True,
            filterable=True,
            group_sql="COALESCE(ls.acronym, ls.name)",
            join_sql=(
                "JOIN publication_structures lps ON lps.publication_id = p.id "
                f"JOIN structures ls ON ls.id = lps.structure_id AND ls.structure_type = '{StructureType.LABO.value}'"
            ),
        ),
        # Forte cardinalité : comparaison et facette (filtre par éditeur, recherche serveur). Jointure interne : exclut les publications sans éditeur.
        Dimension(
            "publisher",
            "Éditeur",
            "high",
            ordinal=False,
            comparable=True,
            filterable=True,
            group_sql="pub.name",
            join_sql="JOIN publishers pub ON pub.id = p.publisher_id",
        ),
        # Forte cardinalité : comparaison et facette (filtre par revue, recherche serveur). Jointure interne : exclut les publications sans revue.
        Dimension(
            "serial",
            "Revue",
            "high",
            ordinal=False,
            comparable=True,
            filterable=True,
            group_sql="jt.title",
            join_sql="JOIN serials jt ON jt.id = p.serial_id",
        ),
        # Forte cardinalité : comparaison et facette (filtre par organisation partenaire, recherche serveur). Une publication compte dans chaque ROR de ses auteurs, ancêtres compris, hors les ROR propres aux laboratoires sélectionnés, ou à tout le périmètre sans sélection.
        Dimension(
            "partner",
            "Organisation partenaire",
            "high",
            ordinal=False,
            comparable=True,
            filterable=True,
            group_sql="pro.name",
            join_sql=(
                "JOIN publication_rors ppr ON ppr.publication_id = p.id "
                f"AND ppr.ror_id NOT IN ({OWN_RORS_SQL}) "
                "JOIN ror_organizations pro ON pro.ror_id = ppr.ror_id"
            ),
        ),
        Dimension("apc", "APC", "low", ordinal=False, comparable=False, filterable=True),
        # Licence de la version éditeur.
        Dimension(
            "license",
            "Licence",
            "low",
            ordinal=False,
            comparable=False,
            filterable=True,
            group_sql=f"COALESCE(p.license::text, '{NO_LICENSE}')",
        ),
    )
}

# Le moteur ventile par l'axe de comparaison (groups).
assert all(d.groupable for d in DIMENSIONS.values() if d.comparable), (
    "une dimension comparable doit être groupable"
)

MEASURES: dict[str, Measure] = {
    m.key: m
    for m in (
        Measure("publication_count", "Nombre de publications", agg_sql="COUNT(*)"),
        # Tous les frais de publication imputés au budget d'une structure du périmètre : APC et frais hors open access.
        Measure(
            "apc_amount",
            "Montant des APC",
            unit="€ HT",
            agg_sql="COALESCE(SUM(apc.amount), 0)::float8",
            join_sql=(
                "LEFT JOIN (SELECT ap.publication_id, SUM(ap.amount_eur_ht) AS amount "
                "FROM apc_payments ap "
                "WHERE ap.budget_structure_id = ANY(CAST(:measure_apc_root_ids AS int[])) "
                "GROUP BY ap.publication_id) apc ON apc.publication_id = g.publication_id"
            ),
        ),
    )
}


@dataclass(frozen=True, slots=True)
class Indicator:
    """Une mesure ventilée par la dimension `breakdown`, empilée dans chaque barre."""

    key: str
    label: str
    measure: str
    breakdown: str


# L'ordre du registre est celui du sélecteur de l'interface.
INDICATORS: dict[str, Indicator] = {
    i.key: i
    for i in (
        Indicator("doc_type_grouped", "Productions", "publication_count", "doc_type_grouped"),
        Indicator("oa_access", "Open access", "publication_count", "oa_access"),
        Indicator("oa_voie", "Modèle OA", "publication_count", "oa_voie"),
        Indicator("license", "Licence", "publication_count", "license"),
        Indicator("apc_amount", "Montant des APC", "apc_amount", "oa_voie"),
    )
}

assert all(
    i.measure in MEASURES
    and DIMENSIONS[i.breakdown].groupable
    and not DIMENSIONS[i.breakdown].comparable
    for i in INDICATORS.values()
), (
    "un indicateur agrège une mesure du registre, ventilée par une dimension groupable non comparable"
)


def validate_pivot(measure: str, groups: Sequence[str]) -> tuple[Measure, list[Dimension]]:
    """Valide une requête de pivot contre le registre (liste blanche).

    Retourne la mesure et les dimensions de groupement résolues. Lève `ValidationError` (→ 400) si une clé est inconnue ou si un groupement est répété — aucune entrée hors du vocabulaire déclaré ne peut atteindre le constructeur SQL.
    """
    if measure not in MEASURES:
        raise ValidationError(f"Mesure inconnue : {measure!r}")
    dims: list[Dimension] = []
    seen: set[str] = set()
    for key in groups:
        if key not in DIMENSIONS:
            raise ValidationError(f"Dimension inconnue : {key!r}")
        if not DIMENSIONS[key].groupable:
            raise ValidationError(f"Dimension non groupable : {key!r}")
        if key in seen:
            raise ValidationError(f"Groupement répété : {key!r}")
        seen.add(key)
        dims.append(DIMENSIONS[key])
    return MEASURES[measure], dims


def validate_indicator(indicator: str, compare: str) -> tuple[str, list[str]]:
    """Résout un indicateur et son axe de comparaison facultatif en mesure et groupements du moteur.

    Lève `ValidationError` si l'indicateur est inconnu ou si `compare` n'est pas une dimension comparable.
    """
    if indicator not in INDICATORS:
        raise ValidationError(f"Indicateur inconnu : {indicator!r}")
    ind = INDICATORS[indicator]
    if not compare:
        return ind.measure, [ind.breakdown]
    if compare not in DIMENSIONS or not DIMENSIONS[compare].comparable:
        raise ValidationError(f"Axe de comparaison inconnu : {compare!r}")
    return ind.measure, [ind.breakdown, compare]


def _order_by(dims: list[Dimension]) -> str:
    """Dimensions ordinales d'abord (ASC, lecture chronologique), puis par la mesure décroissante."""
    parts = [d.key for d in dims if d.ordinal]
    parts.append("value DESC NULLS LAST")
    return ", ".join(parts)


class StatsPivotQueries:
    _conn: Connection

    def pivot_schema(self) -> PivotSchemaResponse:
        return PivotSchemaResponse(
            dimensions=[
                PivotDimensionOut(
                    key=d.key,
                    label=d.label,
                    cardinality=d.cardinality,
                    ordinal=d.ordinal,
                    groupable=d.groupable,
                    comparable=d.comparable,
                    filterable=d.filterable,
                )
                for d in DIMENSIONS.values()
            ],
            indicators=[
                PivotIndicatorOut(
                    key=i.key,
                    label=i.label,
                    unit=MEASURES[i.measure].unit,
                    breakdown=i.breakdown,
                )
                for i in INDICATORS.values()
            ],
        )

    def indicator_pivot(
        self, *, indicator: str, compare: str, filters: PublicationFilters
    ) -> PivotResponse:
        """Exécute l'agrégation d'un indicateur, ventilé par sa dimension puis par `compare` si renseigné."""
        measure, groups = validate_indicator(indicator, compare)
        return self.pivot(measure=measure, groups=groups, filters=filters)

    def pivot(
        self, *, measure: str, groups: list[str], filters: PublicationFilters
    ) -> PivotResponse:
        """Exécute une agrégation : `mesure` ventilée selon `groups`, sous les filtres. Les clés sont validées contre le registre (`validate_pivot`) avant toute composition SQL."""
        m, dims = validate_pivot(measure, groups)
        context = filter_context(self._conn, filters)
        perimeter_structure_ids = context.perimeter_structure_ids
        where, binds = publication_filter_where(filters, context)
        joins = " ".join(dict.fromkeys(d.join_sql for d in dims if d.join_sql))
        inner_select = ", ".join(
            [*[f"{d.group_sql} AS {d.key}" for d in dims], "p.id AS publication_id"]
        )
        inner = (
            f"SELECT DISTINCT {inner_select} FROM publications p "
            f"LEFT JOIN serials j ON j.id = p.serial_id {joins} "
            f"WHERE {where}"
        )
        keys = [d.key for d in dims]
        select = ", ".join([*keys, f"{m.agg_sql} AS value"])
        sql = f"SELECT {select} FROM ({inner}) g {m.join_sql}"
        if dims:
            sql += f" GROUP BY {', '.join(keys)} ORDER BY {_order_by(dims)}"

        self._conn.execute(text("SET LOCAL jit = off"))
        rows = self._conn.execute(
            text(sql),
            {
                **binds,
                "measure_apc_root_ids": perimeter_structure_ids,
                "own_structure_ids": own_structure_ids(filters.lab_ids, perimeter_structure_ids),
            },
        ).all()
        return PivotResponse(
            measure=m.key,
            groups=[d.key for d in dims],
            rows=[dict(r._mapping) for r in rows],
        )
