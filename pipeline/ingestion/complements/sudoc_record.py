"""Lecture des notices Sudoc de publications en série (MARCXML, format UNIMARC).

Une notice décrit une publication sur un support : l'ISSN papier, l'ISSN en ligne et l'ISSN d'un CD-ROM d'une même revue ont chacun leur notice. Les zones lues :

- `011$a` : ISSN de la notice ; `011$y` : ISSN annulé ;
- `183$a` : type de support, `n…` pour le papier, `ceb` pour une ressource en ligne, un autre code pour un autre support (`cde` : CD-ROM). À défaut, `182$c` (`n` papier, `c` électronique) et `135$a`, dont le deuxième caractère `r` désigne une ressource en ligne ;
- `452$x` : ISSN de la même publication sur un autre support ;
- `430$x` : ISSN du titre précédent (suite de) ; `440$x` : ISSN du titre suivant (devient) ;
- `421$x` : ISSN du supplément de la revue ; `422$x` : ISSN de la revue dont elle est le supplément ;
- `200$a`, `200$h`, `200$i` : titre, numéro et nom de la partie (« Physical review » « D »).

Une notice dont le titre nomme le CD-ROM (« The L & O on CD-ROM ») décrit un autre support, quel que soit son codage. Le XML est lu avec `defusedxml`, qui refuse les déclarations d'entités.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import defusedxml.ElementTree as ET

from domain.documents.identifiers import ISSN
from domain.serials.issns import IssnSupport
from domain.sources.sudoc import SudocSerialRecord


@dataclass(frozen=True, slots=True)
class MarcField:
    """Zone de données d'une notice MARC : étiquette et sous-zones `(code, valeur)` dans l'ordre de la notice."""

    tag: str
    subfields: tuple[tuple[str, str], ...]

    def values(self, code: str) -> list[str]:
        """Renvoie les valeurs des sous-zones de code `code`."""
        return [value for c, value in self.subfields if c == code]


class NotMarcRecordError(ValueError):
    """Le document XML est autre chose qu'une notice `<record>`, par exemple un message d'erreur du Sudoc."""


def marc_fields(xml: str) -> list[MarcField]:
    """Lit les zones de données d'une notice MARCXML, dans l'ordre de la notice. Lève `NotMarcRecordError` si la racine est autre chose que `<record>`."""
    root = ET.fromstring(xml)
    root_name = root.tag.rsplit("}", 1)[-1]
    if root_name != "record":
        raise NotMarcRecordError(f"racine <{root_name}>")
    fields: list[MarcField] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "datafield":
            continue
        subfields = tuple(
            (sub.get("code") or "", (sub.text or "").strip())
            for sub in element
            if sub.tag.rsplit("}", 1)[-1] == "subfield"
        )
        fields.append(MarcField(tag=element.get("tag") or "", subfields=subfields))
    return fields


_OTHER_SUPPORT_WORDS = ("cd-rom", "cdrom", "cédérom")
"""Le CD-ROM se reconnaît aussi dans le titre de la notice."""


def _issns(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(issn) for v in values if (issn := ISSN.try_parse(v))))


def _subfield_values(fields: Sequence[MarcField], tag: str, code: str) -> list[str]:
    return [value for field in fields if field.tag == tag for value in field.values(code)]


def _support(fields: Sequence[MarcField]) -> IssnSupport | None:
    carriers = _subfield_values(fields, "183", "a")
    if carriers:
        if carriers[0].startswith("n"):
            return IssnSupport.PRINT
        return IssnSupport.ELECTRONIC if carriers[0] == "ceb" else IssnSupport.OTHER
    mediation = _subfield_values(fields, "182", "c")
    if not mediation:
        return None
    if mediation[0] == "n":
        return IssnSupport.PRINT
    coded = _subfield_values(fields, "135", "a")
    if mediation[0] == "c" and coded and coded[0][1:2] == "r":
        return IssnSupport.ELECTRONIC
    return IssnSupport.OTHER


def _names_other_support(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _OTHER_SUPPORT_WORDS)


def _title(fields: Sequence[MarcField]) -> str | None:
    first = next((f for f in fields if f.tag == "200"), None)
    if first is None:
        return None
    parts = first.values("a")[:1] + first.values("h") + first.values("i")
    return " ".join(p for p in parts if p) or None


def parse_sudoc_serial_record(ppn: str, fields: Sequence[MarcField]) -> SudocSerialRecord:
    """Lit une notice Sudoc de publication en série. Une zone absente donne `None` ou un tuple vide."""
    issns = _issns(_subfield_values(fields, "011", "a"))
    title = _title(fields)
    return SudocSerialRecord(
        ppn=ppn,
        issn=issns[0] if issns else None,
        cancelled_issns=_issns(_subfield_values(fields, "011", "y")),
        support=IssnSupport.OTHER if title and _names_other_support(title) else _support(fields),
        other_support_issns=_issns(_subfield_values(fields, "452", "x")),
        title=title,
        continues=_issns(_subfield_values(fields, "430", "x")),
        continued_by=_issns(_subfield_values(fields, "440", "x")),
        supplements=_issns(_subfield_values(fields, "421", "x")),
        supplement_of=_issns(_subfield_values(fields, "422", "x")),
    )
