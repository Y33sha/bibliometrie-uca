"""ISSN : support et statut de chaque valeur, ISSN donnés par une source."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from domain.publications.identifiers import ISSN


class IssnSupport(StrEnum):
    """Support d'une publication en série."""

    PRINT = "print"
    ELECTRONIC = "electronic"
    """Ressource en ligne."""
    OTHER = "other"
    """Autre support : CD-ROM, microforme…"""


class IssnStatus(StrEnum):
    """Statut d'un ISSN dans `serial_issns`."""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    UNVERIFIED = "unverified"
    """ISSN sans notice Sudoc."""


ISSN_SUPPORTS = tuple(IssnSupport)
ISSN_STATUSES = tuple(IssnStatus)


@dataclass(frozen=True, slots=True, kw_only=True)
class SerialIssn:
    """Un ISSN d'une série, tel que la source le donne."""

    issn: str
    support: IssnSupport | None = None
    linking: bool = False
    """Vrai pour l'ISSN-L."""
    malformed: bool = False
    """Forme ou clé de contrôle fausse : la valeur est gardée telle que reçue."""


def received_issns(issns: Iterable[SerialIssn]) -> tuple[SerialIssn, ...]:
    """Normalise les ISSN reçus d'une source, et retire les doublons.

    Une valeur invalide garde sa forme reçue et est marquée mal formée. Deux mentions d'une même valeur n'en font qu'une : le premier support connu, le drapeau ISSN-L de l'une ou l'autre.
    """
    rows: dict[str, SerialIssn] = {}
    for row in issns:
        raw = row.issn.strip()
        if not raw:
            continue
        issn = ISSN.try_parse(raw)
        value = str(issn) if issn else raw
        if value in rows:
            known = rows[value]
            rows[value] = SerialIssn(
                issn=value,
                support=known.support or row.support,
                linking=known.linking or row.linking,
                malformed=known.malformed,
            )
        else:
            rows[value] = SerialIssn(
                issn=value,
                support=row.support,
                linking=row.linking and issn is not None,
                malformed=issn is None,
            )
    return tuple(rows.values())


def source_issns(
    *,
    print_issn: str | None = None,
    electronic_issn: str | None = None,
    unknown: Iterable[str | None] = (),
    linking: str | None = None,
) -> tuple[SerialIssn, ...]:
    """Construit les ISSN donnés par une source : papier, en ligne, ou de support inconnu.

    Args:
        linking: ISSN-L.
    """
    return received_issns(
        [
            *(
                SerialIssn(issn=value, support=support)
                for value, support in (
                    (print_issn, IssnSupport.PRINT),
                    (electronic_issn, IssnSupport.ELECTRONIC),
                )
                if value
            ),
            *(SerialIssn(issn=value) for value in unknown if value),
            *([SerialIssn(issn=linking, linking=True)] if linking else []),
        ]
    )
