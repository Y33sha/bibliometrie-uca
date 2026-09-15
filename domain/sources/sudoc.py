"""Interprétation des notices Sudoc de publications en série (format UNIMARC).

Une notice décrit une publication sur un support : l'ISSN papier et l'ISSN électronique d'une même revue ont chacun leur notice, reliées par l'ISSN-L. Les zones lues :

- `011$a` : ISSN de la notice ; `011$f` : ISSN-L ; `011$y` : ISSN annulé ;
- `182$c` : support, `n` pour le papier, `c` pour l'électronique ;
- `452$x` : ISSN de la même publication sur l'autre support ;
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


# Code de type de médiation (`182$c`) → support.
_MEDIATION_SUPPORT = {"n": Support.PRINT, "c": Support.ELECTRONIC}


@dataclass(frozen=True, slots=True)
class SudocSerialRecord:
    """Ce que le pipeline lit dans une notice Sudoc de publication en série. Les ISSN sont normalisés ; une valeur invalide est ignorée."""

    ppn: str
    issn: str | None
    issnl: str | None
    cancelled_issns: tuple[str, ...]
    support: Support | None
    other_support_issns: tuple[str, ...]
    title: str | None


def _issns(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(issn) for v in values if (issn := ISSN.try_parse(v))))


def _subfield_values(fields: Sequence[MarcField], tag: str, code: str) -> list[str]:
    return [value for field in fields if field.tag == tag for value in field.values(code)]


def parse_sudoc_serial_record(ppn: str, fields: Sequence[MarcField]) -> SudocSerialRecord:
    """Lit une notice Sudoc de publication en série. Une zone absente donne `None` ou un tuple vide."""
    issns = _issns(_subfield_values(fields, "011", "a"))
    issnls = _issns(_subfield_values(fields, "011", "f"))
    supports = [
        _MEDIATION_SUPPORT[code]
        for code in _subfield_values(fields, "182", "c")
        if code in _MEDIATION_SUPPORT
    ]
    titles = _subfield_values(fields, "200", "a")
    return SudocSerialRecord(
        ppn=ppn,
        issn=issns[0] if issns else None,
        issnl=issnls[0] if issnls else None,
        cancelled_issns=_issns(_subfield_values(fields, "011", "y")),
        support=supports[0] if supports else None,
        other_support_issns=_issns(_subfield_values(fields, "452", "x")),
        title=titles[0] if titles else None,
    )
