"""Neutralisation, pour la détection de changement, de ce qui varie dans un nœud DataCite sans que la notice change.

Un même DOI se lit par deux routes : la liste (`/dois?query=…`, extraction et phase `fetch_missing`) et la route unitaire (`/dois/{doi}`, phase `fetch_stale`). La route unitaire ajoute la notice XML encodée (`xml`), `prefix`, `suffix`, `published`, des `relationships` détaillées, rend `[]` là où la liste rend `None`, et donne les dates à la milliseconde. Les compteurs de consultation et de citation (`…Count`, `…OverTime`) bougent d'une lecture à l'autre.

`strip_volatile_for_hash` renvoie une copie du nœud sans ces champs, à seule fin de calculer le hash. Les métadonnées lues par la normalisation restent dans le hash : une modification réelle de la notice reste détectée. Le payload stocké reste fidèle à la source.
"""

from collections.abc import Mapping

from domain.types import JsonValue

# Attributs absents d'une route ou propres à l'enregistrement du DOI, qu'aucune lecture n'utilise.
_ROUTE_OR_REGISTRATION = frozenset(
    {"xml", "prefix", "suffix", "published", "created", "registered", "updated"}
)
# Suffixes des compteurs de consultation, de téléchargement et de citation.
_COUNTER_SUFFIXES = ("Count", "OverTime")


def _kept(key: str, value: JsonValue) -> bool:
    if key in _ROUTE_OR_REGISTRATION or key.endswith(_COUNTER_SUFFIXES):
        return False
    return value not in (None, [])


def strip_volatile_for_hash(raw_data: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    """Copie du nœud DataCite réduite à `id`, `type` et aux attributs stables, sans `relationships`."""
    attributes = raw_data.get("attributes")
    stable: dict[str, JsonValue] = {"id": raw_data.get("id"), "type": raw_data.get("type")}
    if isinstance(attributes, Mapping):
        stable["attributes"] = {k: v for k, v in attributes.items() if _kept(k, v)}
    return stable
