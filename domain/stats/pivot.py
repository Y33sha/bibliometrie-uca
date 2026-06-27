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
  (une publication a plusieurs sources : grouper par `source` la compte dans chacune). Dès
  qu'un groupement démultiplie, la mesure doit compter les publications de façon distincte.
- **`is_ratio`** (mesure) — mesure-ratio (un numérateur sur un dénominateur, p. ex. le taux
  d'accès ouvert : une courbe) vs agrégat additif (empilable).

Pur, sans I/O. Ajouter une dimension ou une mesure = ajouter une entrée ici (et sa liaison
SQL côté infrastructure).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from domain.errors import ValidationError

Cardinality = Literal["low", "high"]


@dataclass(frozen=True, slots=True)
class Dimension:
    """Un axe de groupement / ventilation."""

    key: str
    label: str
    cardinality: Cardinality
    ordinal: bool
    multiplies: bool


@dataclass(frozen=True, slots=True)
class Measure:
    """Une grandeur agrégée."""

    key: str
    label: str
    is_ratio: bool


DIMENSIONS: dict[str, Dimension] = {
    "year": Dimension("year", "Année", "low", ordinal=True, multiplies=False),
    "oa_access": Dimension("oa_access", "Accès", "low", ordinal=False, multiplies=False),
    "oa_voie": Dimension("oa_voie", "Voie d'accès ouvert", "low", ordinal=False, multiplies=False),
    "doc_type": Dimension("doc_type", "Type de document", "low", ordinal=False, multiplies=False),
    "source": Dimension("source", "Source", "low", ordinal=False, multiplies=True),
}

MEASURES: dict[str, Measure] = {
    "pub_count": Measure("pub_count", "Nombre de publications", is_ratio=False),
    "pct_open": Measure("pct_open", "% d'accès ouvert", is_ratio=True),
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
        if key in seen:
            raise ValidationError(f"Groupement répété : {key!r}")
        seen.add(key)
        dims.append(DIMENSIONS[key])
    return MEASURES[measure], dims


def grain_multiplies(dims: Sequence[Dimension]) -> bool:
    """Vrai si au moins une dimension du groupement démultiplie une publication — la mesure
    doit alors compter les publications de façon distincte (`COUNT(DISTINCT publication_id)`)."""
    return any(d.multiplies for d in dims)
