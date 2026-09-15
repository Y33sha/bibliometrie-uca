"""Interprétation des notices Sudoc de publications en série (format UNIMARC).

Une notice décrit une publication sur un support : l'ISSN papier, l'ISSN en ligne et l'ISSN d'un CD-ROM d'une même revue ont chacun leur notice. Les zones lues :

- `011$a` : ISSN de la notice ; `011$f` : ISSN-L ; `011$y` : ISSN annulé ;
- `183$a` : type de support, `n…` pour le papier, `ceb` pour une ressource en ligne, un autre code pour un autre support (`cde` : CD-ROM). À défaut, `182$c` (`n` papier, `c` électronique) et `135$a`, dont le deuxième caractère `r` désigne une ressource en ligne ;
- `452$x` : ISSN de la même publication sur un autre support ;
- `430$x` à `437$x` : ISSN des titres précédents ; `440$x` à `448$x` : ISSN des titres suivants ;
- `200$a` : titre.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from domain.publications.identifiers import ISSN


@dataclass(frozen=True, slots=True)
class MarcField:
    """Zone d'une notice MARC : étiquette, indicateurs et sous-zones `(code, valeur)` dans l'ordre de la notice."""

    tag: str
    ind1: str
    ind2: str
    subfields: tuple[tuple[str, str], ...]

    def values(self, code: str) -> list[str]:
        """Valeurs des sous-zones de code `code`."""
        return [value for c, value in self.subfields if c == code]


class Support(StrEnum):
    """Support d'une publication en série."""

    PRINT = "print"
    ELECTRONIC = "electronic"
    """Ressource en ligne."""
    OTHER = "other"
    """Autre support : CD-ROM, microforme…"""


_PRECEDING_TAGS = frozenset(str(t) for t in range(430, 438))
_SUCCEEDING_TAGS = frozenset(str(t) for t in range(440, 449))


@dataclass(frozen=True, slots=True)
class SudocSerialRecord:
    """Ce que le pipeline lit dans une notice Sudoc de publication en série. Les ISSN sont normalisés ; une valeur invalide est ignorée."""

    ppn: str
    issn: str | None
    issnl: str | None
    cancelled_issns: tuple[str, ...]
    support: Support | None
    other_support_issns: tuple[str, ...]
    preceding_issns: tuple[str, ...]
    succeeding_issns: tuple[str, ...]
    title: str | None


def _issns(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(issn) for v in values if (issn := ISSN.try_parse(v))))


def _subfield_values(
    fields: Sequence[MarcField], tags: str | frozenset[str], code: str
) -> list[str]:
    wanted = frozenset({tags}) if isinstance(tags, str) else tags
    return [value for field in fields if field.tag in wanted for value in field.values(code)]


def _support(fields: Sequence[MarcField]) -> Support | None:
    carriers = _subfield_values(fields, "183", "a")
    if carriers:
        if carriers[0].startswith("n"):
            return Support.PRINT
        return Support.ELECTRONIC if carriers[0] == "ceb" else Support.OTHER
    mediation = _subfield_values(fields, "182", "c")
    if not mediation:
        return None
    if mediation[0] == "n":
        return Support.PRINT
    coded = _subfield_values(fields, "135", "a")
    if mediation[0] == "c" and coded and coded[0][1:2] == "r":
        return Support.ELECTRONIC
    return Support.OTHER


def parse_sudoc_serial_record(ppn: str, fields: Sequence[MarcField]) -> SudocSerialRecord:
    """Lit une notice Sudoc de publication en série. Une zone absente donne `None` ou un tuple vide."""
    issns = _issns(_subfield_values(fields, "011", "a"))
    issnls = _issns(_subfield_values(fields, "011", "f"))
    titles = _subfield_values(fields, "200", "a")
    return SudocSerialRecord(
        ppn=ppn,
        issn=issns[0] if issns else None,
        issnl=issnls[0] if issnls else None,
        cancelled_issns=_issns(_subfield_values(fields, "011", "y")),
        support=_support(fields),
        other_support_issns=_issns(_subfield_values(fields, "452", "x")),
        preceding_issns=_issns(_subfield_values(fields, _PRECEDING_TAGS, "x")),
        succeeding_issns=_issns(_subfield_values(fields, _SUCCEEDING_TAGS, "x")),
        title=titles[0] if titles else None,
    )
