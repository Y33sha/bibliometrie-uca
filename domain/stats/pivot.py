"""Registre du pivot : vocabulaire abstrait des dimensions et des mesures.

Décrit *ce qu'on peut grouper, ventiler et mesurer* sur le corpus de publications,
indépendamment de toute requête. C'est l'artefact central du moteur de pivot : une vue
de système est une **mesure** agrégée selon un ou plusieurs **groupements**, sous des
filtres. Ici on ne décrit que le vocabulaire et ses propriétés ; l'infrastructure y
associe une liaison SQL, l'interface y lit ses sélecteurs.

Propriétés portées par le registre :

- **cardinalité** — `low` (peu de valeurs, *graphable* sur un axe) vs `high` (milliers de
  valeurs : table classée ou graphique tronqué aux N premières).
- **ordinal** — axe ordonné (l'année) vs catégoriel (la voie d'accès), qui change le tri
  et l'éligibilité au filtrage par plage.
- **`multiplies`** (grain) — grouper par cette dimension démultiplie-t-il une publication ?
  (une publication rattachée à plusieurs laboratoires compte dans chacun). Dès qu'un groupement
  démultiplie, la mesure doit compter les publications de façon distincte.
- **`groupable` / `filterable`** — rôles d'une dimension : axe de ventilation et/ou facette. La
  barre de facettes se *dérive* de l'ensemble des dimensions filtrables (`applicable_facets`), sans
  table de combinaisons (mesure, groupement).

La grandeur affichée est toujours un compte de publications (`COUNT(DISTINCT publication_id)`). Le
taux d'accès ouvert n'est pas une mesure à part : il se lit en comparant par accès puis en aplatissant
à 100 %, ou comme colonne triable d'un classement d'entités.

Pur, sans I/O. Ajouter une dimension ou une mesure = ajouter une entrée ici (et sa liaison
SQL côté infrastructure si elle est groupable).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from domain.errors import ValidationError

Cardinality = Literal["low", "high"]


@dataclass(frozen=True, slots=True)
class Dimension:
    """Un attribut d'une publication et ses rôles possibles :

    - `groupable` : axe de ventilation (la catégorie empilée dans chaque barre) ;
    - `comparable` : axe de comparaison (l'abscisse, ce qu'on compare d'une valeur à l'autre —
      l'année, les laboratoires, les éditeurs, les revues). L'accès et la voie d'accès se groupent
      (empilent) mais ne se comparent pas ; un axe comparable est toujours groupable (le moteur
      ventile par lui) ;
    - `filterable` : facette. Certaines dimensions sont filtrables seules (APC : utile à filtrer,
      sans intérêt comme axe)."""

    key: str
    label: str
    cardinality: Cardinality
    ordinal: bool
    multiplies: bool
    groupable: bool
    comparable: bool
    filterable: bool


@dataclass(frozen=True, slots=True)
class Measure:
    """Une grandeur agrégée. Le registre n'en porte qu'une : le compte des publications. Le taux
    d'accès ouvert relève de la présentation (part à 100 %) ou d'une colonne de classement, pas d'une
    mesure."""

    key: str
    label: str


DIMENSIONS: dict[str, Dimension] = {
    "year": Dimension(
        "year", "Année", "low",
        ordinal=True, multiplies=False, groupable=True, comparable=True, filterable=True,
    ),
    "oa_access": Dimension(
        "oa_access", "Open access", "low",
        ordinal=False, multiplies=False, groupable=True, comparable=False, filterable=False,
    ),
    "oa_voie": Dimension(
        "oa_voie", "Modèle OA", "low",
        ordinal=False, multiplies=False, groupable=True, comparable=False, filterable=True,
    ),
    "doc_type": Dimension(
        "doc_type", "Type de document", "low",
        ordinal=False, multiplies=False, groupable=False, comparable=False, filterable=True,
    ),
    "doc_type_grouped": Dimension(
        "doc_type_grouped", "Productions", "low",
        ordinal=False, multiplies=False, groupable=True, comparable=True, filterable=False,
    ),
    "lab": Dimension(
        "lab", "Laboratoire", "high",
        ordinal=False, multiplies=True, groupable=True, comparable=True, filterable=True,
    ),  # forte cardinalité : comparaison paginée, pas de groupement primaire
    "publisher": Dimension(
        "publisher", "Éditeur", "high",
        ordinal=False, multiplies=False, groupable=True, comparable=True, filterable=True,
    ),  # forte cardinalité : comparaison et facette (filtre par éditeur, recherche serveur)
    "journal": Dimension(
        "journal", "Revue", "high",
        ordinal=False, multiplies=False, groupable=True, comparable=True, filterable=True,
    ),  # forte cardinalité : comparaison et facette (filtre par revue, recherche serveur)
    "apc": Dimension(
        "apc", "APC", "low",
        ordinal=False, multiplies=False, groupable=False, comparable=False, filterable=True,
    ),
}

# Un axe de comparaison est toujours groupable : le moteur ventile par lui (groups).
assert all(d.groupable for d in DIMENSIONS.values() if d.comparable), (
    "une dimension comparable doit être groupable"
)

MEASURES: dict[str, Measure] = {
    "pub_count": Measure("pub_count", "Nombre de publications"),
}


def validate_pivot(measure: str, groups: Sequence[str]) -> tuple[Measure, list[Dimension]]:
    """Valide une requête de pivot contre le registre (liste blanche).

    Retourne la mesure et les dimensions de groupement résolues. Lève `ValidationError`
    (→ 400) si une clé est inconnue ou si un groupement est répété — aucune autre entrée
    que le vocabulaire déclaré ne peut atteindre le constructeur SQL.
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


def applicable_facets(measure_key: str, group_keys: Sequence[str]) -> list[str]:
    """Facettes applicables à une vue, par soustraction d'un ensemble universel (cf. registre).

    Part de toutes les dimensions `filterable`, puis retire — **règle G** — un groupement *catégoriel*
    (un axe de ventilation déjà visible ; un groupement *ordinal* comme l'année reste filtrable en plage).

    Aucune table de combinaisons : un ensemble unique moins ce que les groupements consomment.
    """
    if measure_key not in MEASURES:
        raise ValidationError(f"Mesure inconnue : {measure_key!r}")
    grouped = set(group_keys)
    out: list[str] = []
    for dim in DIMENSIONS.values():
        if not dim.filterable:
            continue
        if dim.key in grouped and not dim.ordinal:
            continue
        out.append(dim.key)
    return out


def grain_multiplies(dims: Sequence[Dimension]) -> bool:
    """Vrai si au moins une dimension du groupement démultiplie une publication — la mesure
    doit alors compter les publications de façon distincte (`COUNT(DISTINCT publication_id)`)."""
    return any(d.multiplies for d in dims)
