"""Faits sur un ISSN tirés de sa notice Sudoc : ISSN-L, support, statut, liens vers d'autres ISSN."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from domain.serials.issns import IssnStatus, IssnSupport
from domain.sources.sudoc import SudocSerialRecord


class IssnLinkType(StrEnum):
    """Lien entre deux ISSN, toujours écrit dans le même sens."""

    CONTINUED_BY = "continued_by"
    """Titre précédent vers titre suivant."""
    SUPPLEMENT = "supplement"
    """Revue principale vers supplément."""


ISSN_LINK_TYPES = tuple(IssnLinkType)


@dataclass(frozen=True, slots=True)
class IssnFacts:
    """Ligne de `serial_issns` d'après le Sudoc."""

    issn: str
    issnl: str | None
    support: IssnSupport | None
    status: IssnStatus


@dataclass(frozen=True, slots=True)
class IssnLink:
    """Lien d'un ISSN vers un autre."""

    issn: str
    linked_issn: str
    link_type: IssnLinkType


@dataclass(frozen=True, slots=True)
class SudocReading:
    """Lecture de la notice Sudoc d'un ISSN."""

    facts: tuple[IssnFacts, ...]
    links: tuple[IssnLink, ...] = ()
    title: str | None = None
    other_support_issns: tuple[str, ...] = ()
    """ISSN de la même publication sur un autre support, à vérifier à leur tour."""

    @property
    def issnl(self) -> str | None:
        """ISSN-L de l'ISSN lu."""
        return self.facts[0].issnl


def read_sudoc_record(issn: str, record: SudocSerialRecord | None) -> SudocReading:
    """Renvoie les faits sur `issn` tirés de sa notice Sudoc, `record`, éventuellement absente.

    Sans notice Sudoc, l'ISSN est `unverified`. La notice Sudoc donne l'ISSN-L de `issn`, de son propre ISSN quand il diffère, et de ses ISSN annulés. Les zones 430, 440, 421 et 422 donnent les liens, orientés du titre précédent vers le titre suivant, de la revue principale vers le supplément.
    """
    if record is None:
        return SudocReading((IssnFacts(issn, None, None, IssnStatus.UNVERIFIED),))
    cancelled = set(record.cancelled_issns)
    facts = [
        IssnFacts(
            issn,
            record.issnl,
            record.support if record.issn == issn else None,
            IssnStatus.CANCELLED if issn in cancelled else IssnStatus.ACTIVE,
        )
    ]
    if record.issn and record.issn != issn:
        facts.append(IssnFacts(record.issn, record.issnl, record.support, IssnStatus.ACTIVE))
    facts += [
        IssnFacts(c, record.issnl, None, IssnStatus.CANCELLED)
        for c in record.cancelled_issns
        if c not in (issn, record.issn)
    ]
    own = record.issn or issn
    links = [
        *(IssnLink(p, own, IssnLinkType.CONTINUED_BY) for p in record.continues),
        *(IssnLink(own, s, IssnLinkType.CONTINUED_BY) for s in record.continued_by),
        *(IssnLink(own, s, IssnLinkType.SUPPLEMENT) for s in record.supplements),
        *(IssnLink(m, own, IssnLinkType.SUPPLEMENT) for m in record.supplement_of),
    ]
    return SudocReading(
        tuple(facts),
        tuple(dict.fromkeys(link for link in links if link.issn != link.linked_issn)),
        record.title,
        tuple(i for i in record.other_support_issns if i not in (issn, record.issn)),
    )
