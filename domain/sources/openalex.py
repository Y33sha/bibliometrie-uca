"""Source OpenAlex d'une publication en série (`/sources`) et liste de revues d'OpenAlex (`/source-lists`)."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class OpenAlexSource:
    """Source OpenAlex, réduite aux champs lus. Les ISSN sont normalisés ; une valeur invalide est ignorée."""

    id: str
    """Identifiant court (`S137773608`)."""
    issns: tuple[str, ...]
    type: str | None
    """Type de source dans le vocabulaire d'OpenAlex : `journal`, `conference`, `book series`…"""
    listed_in: tuple[str, ...]
    """Codes des listes de revues où figure la source."""
    works_count: int


@dataclass(frozen=True, slots=True)
class OpenAlexSourceList:
    """Liste de revues d'OpenAlex, réduite aux champs lus."""

    code: str
    """Code de la liste dans `listed_in`."""
    maintainer: str | None
    url: str | None
    edition: date | None
    """Date de l'édition chargée par OpenAlex."""
