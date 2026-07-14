"""Registre du pivot : vocabulaire abstrait des dimensions et des mesures.

Décrit ce qu'on peut grouper, ventiler et mesurer sur le corpus de publications, indépendamment de toute requête : une vue est une **mesure** agrégée selon un ou plusieurs **groupements**, sous des filtres. On ne décrit ici que le vocabulaire ; l'infrastructure y associe une liaison SQL, l'interface y lit ses sélecteurs.

Propriétés d'une dimension :
- **cardinalité** — `low` (peu de valeurs, portables sur un axe) ou `high` (milliers de valeurs : table classée ou top-N).
- **ordinal** — axe ordonné (l'année) ou catégoriel, qui change le tri et l'éligibilité au filtrage par plage.
- **groupable / comparable / filterable** — rôles : catégorie de ventilation, axe de comparaison (abscisse), facette. Un axe comparable est toujours groupable.

La grandeur est toujours un compte de publications (`COUNT(DISTINCT publication_id)`) ; le taux d'accès ouvert relève de la présentation, pas d'une mesure à part.

Pur, sans I/O. Ajouter une dimension ou une mesure = une entrée ici (et sa liaison SQL côté infrastructure si elle est groupable).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from domain.errors import ValidationError

Cardinality = Literal["low", "high"]


@dataclass(frozen=True, slots=True)
class Dimension:
    """Un attribut d'une publication et ses rôles possibles :

    - `groupable` : catégorie de ventilation (empilée dans chaque barre) ;
    - `comparable` : axe de comparaison (l'abscisse : l'année, les laboratoires, les éditeurs, les revues). L'accès et la voie d'accès se groupent mais ne se comparent pas ; un axe comparable est toujours groupable ;
    - `filterable` : facette. Certaines dimensions ne sont que filtrables (APC : utile en filtre, sans intérêt comme axe)."""

    key: str
    label: str
    cardinality: Cardinality
    ordinal: bool
    groupable: bool
    comparable: bool
    filterable: bool


@dataclass(frozen=True, slots=True)
class Measure:
    """Une grandeur agrégée. Le registre n'en porte qu'une : le compte des publications. Le taux d'accès ouvert relève de la présentation (part à 100 %) ou d'une colonne de classement."""

    key: str
    label: str


DIMENSIONS: dict[str, Dimension] = {
    "year": Dimension(
        "year", "Année", "low", ordinal=True, groupable=True, comparable=True, filterable=True
    ),
    "oa_access": Dimension(
        "oa_access",
        "Open access",
        "low",
        ordinal=False,
        groupable=True,
        comparable=False,
        filterable=False,
    ),
    "oa_voie": Dimension(
        "oa_voie",
        "Modèle OA",
        "low",
        ordinal=False,
        groupable=True,
        comparable=False,
        filterable=True,
    ),
    "doc_type": Dimension(
        "doc_type",
        "Type de document",
        "low",
        ordinal=False,
        groupable=False,
        comparable=False,
        filterable=True,
    ),
    "doc_type_grouped": Dimension(
        "doc_type_grouped",
        "Productions",
        "low",
        ordinal=False,
        groupable=True,
        comparable=False,
        filterable=False,
    ),
    "lab": Dimension(
        "lab",
        "Laboratoire",
        "high",
        ordinal=False,
        groupable=True,
        comparable=True,
        filterable=True,
    ),  # forte cardinalité : comparaison paginée, pas de groupement primaire
    "publisher": Dimension(
        "publisher",
        "Éditeur",
        "high",
        ordinal=False,
        groupable=True,
        comparable=True,
        filterable=True,
    ),  # forte cardinalité : comparaison et facette (filtre par éditeur, recherche serveur)
    "journal": Dimension(
        "journal", "Revue", "high", ordinal=False, groupable=True, comparable=True, filterable=True
    ),  # forte cardinalité : comparaison et facette (filtre par revue, recherche serveur)
    "apc": Dimension(
        "apc", "APC", "low", ordinal=False, groupable=False, comparable=False, filterable=True
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
