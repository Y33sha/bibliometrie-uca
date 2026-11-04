"""Source OpenAlex d'une revue : type de revue d'un type de source, source retenue parmi celles des ISSN de la revue, revue qui reçoit un identifiant réclamé par plusieurs revues."""

from collections.abc import Iterable
from typing import NamedTuple

from domain.serials.serial import SerialType
from domain.sources.openalex import OpenAlexSource

_SERIAL_TYPES: dict[str, SerialType] = {
    "journal": SerialType.JOURNAL,
    "conference": SerialType.PROCEEDINGS,
    "book series": SerialType.BOOK_SERIES,
}


def serial_type_of_source(source_type: str | None) -> SerialType | None:
    """Renvoie le type de revue d'un type de source OpenAlex, ou `None` pour un type sans équivalent : `repository`, `metadata`, `other`, `ebook platform`, type inconnu. `media` se pose à la main."""
    return _SERIAL_TYPES.get(source_type.lower()) if source_type else None


def main_source(sources: Iterable[OpenAlexSource]) -> OpenAlexSource | None:
    """Renvoie la source qui a le plus de works, à égalité le plus petit identifiant, ou `None` sans source."""
    return min(sources, key=lambda s: (-s.works_count, s.id), default=None)


class Claimant(NamedTuple):
    """Revue qui réclame un identifiant OpenAlex."""

    serial_id: int
    publication_count: int


def holder(claimants: Iterable[Claimant]) -> int:
    """Renvoie la revue qui reçoit un identifiant OpenAlex : celle qui a le plus de publications, à égalité le plus petit identifiant."""
    return min(claimants, key=lambda c: (-c.publication_count, c.serial_id)).serial_id
