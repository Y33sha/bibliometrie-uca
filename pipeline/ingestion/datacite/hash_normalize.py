"""Neutralisation, pour la détection de changement, de ce qui varie dans une ressource DataCite sans que l'enregistrement change.

Un même DOI se lit par deux routes : la liste (`/dois?query=…`, moissonnage et phase `fetch_missing`) et la route unitaire (`/dois/{doi}`, phase `fetch_stale`). La route unitaire ajoute l'enregistrement XML encodé (`xml`), `prefix`, `suffix`, `published`, des `relationships` détaillées, renvoie `[]` là où la liste renvoie `None`, et donne les dates à la milliseconde. Les compteurs (`…Count`, `…OverTime`) bougent d'une lecture à l'autre ; seul le nombre de citations, que la normalisation lit, reste dans l'empreinte.

`strip_volatile_for_hash` renvoie une copie de la ressource sans ces champs, pour le seul calcul de l'empreinte. Les métadonnées que lit la normalisation restent dans l'empreinte : un vrai changement de l'enregistrement reste détecté. Le payload stocké reste fidèle à la source.
"""

from collections.abc import Mapping

from domain.types import JsonValue

# Attributs absents d'une route ou propres à l'enregistrement du DOI, qu'aucune lecture n'utilise.
_ROUTE_OR_REGISTRATION = frozenset(
    {"xml", "prefix", "suffix", "published", "created", "registered", "updated"}
)
# Suffixes des compteurs (consultations, téléchargements, références, versions…).
_COUNTER_SUFFIXES = ("Count", "OverTime")
# Compteur que la normalisation lit : il reste dans l'empreinte.
_READ_COUNTERS = frozenset({"citationCount"})


def _kept(key: str, value: JsonValue) -> bool:
    if key in _ROUTE_OR_REGISTRATION:
        return False
    if key.endswith(_COUNTER_SUFFIXES) and key not in _READ_COUNTERS:
        return False
    return value not in (None, [])


def strip_volatile_for_hash(raw_data: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    """Copie de la ressource DataCite réduite à `id`, `type` et aux attributs stables, sans `relationships`."""
    attributes = raw_data.get("attributes")
    stable: dict[str, JsonValue] = {"id": raw_data.get("id"), "type": raw_data.get("type")}
    if isinstance(attributes, Mapping):
        stable["attributes"] = {k: v for k, v in attributes.items() if _kept(k, v)}
    return stable
