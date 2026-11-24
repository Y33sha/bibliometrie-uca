"""Neutralisation, pour la détection de changement, des champs variables d'une œuvre Crossref à métadonnées inchangées.

Un même DOI se lit par deux routes : la recherche (`/works?filter=…`, phase `harvest_by_person`) et la route unitaire (`/works/{doi}`, phases `fetch_missing` et `fetch_stale`). La recherche ajoute un score de pertinence (`score`) et renvoie `None` là où la route unitaire renvoie `[]` ou `{}`. Crossref horodate chaque réindexation (`indexed`), chaque dépôt de l'éditeur (`deposited`) et la création du DOI (`created`), sans changement des métadonnées lues par la normalisation.

`strip_volatile_for_hash` renvoie une copie de l'œuvre sans ces champs, pour le seul calcul de l'empreinte. Le payload stocké reste fidèle à la source.
"""

from collections.abc import Mapping

from domain.types import JsonValue

_VOLATILE = frozenset({"score", "indexed", "deposited", "created"})
"""Score de pertinence de la recherche et horodatages de Crossref, inutilisés par la normalisation."""


def strip_volatile_for_hash(raw_data: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    """Renvoie une copie de l'œuvre Crossref sans les champs variables ni les champs vides."""
    return {k: v for k, v in raw_data.items() if k not in _VOLATILE and v not in (None, [], {})}
