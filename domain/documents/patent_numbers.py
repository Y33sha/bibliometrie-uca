"""Lecture des numéros de brevet d'un texte libre, comme le champ `number_s` d'un dépôt HAL.

Un numéro lu est un numéro de publication ou de demande, sous la forme de `PatentNumber` : code de l'office, puis le numéro, sans code de type. La forme d'un numéro de demande suit le format docdb de l'Office européen des brevets, lu par la source OPS :

- demande internationale : `WO`, l'année sur quatre chiffres, puis le numéro sur six chiffres, sans l'office de dépôt (`PCT/FR2025/050875` → `WO2025050875`) ;
- demande européenne : `EP`, puis huit chiffres, sans le chiffre de contrôle (`EP21306403.3` → `EP21306403`) ;
- demande française : `FR`, l'année sur deux chiffres, puis cinq chiffres (`FR19/04067` → `FR1904067`).

Un nombre sans office est lu comme un numéro français, sauf un nombre de huit chiffres suivi d'un chiffre de contrôle, lu comme une demande européenne. Une référence interne (`DI-RV-22-0027`) est écartée.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from domain.documents.identifiers import PatentNumber


class PatentNumberKind(StrEnum):
    """Étape désignée par un numéro de brevet."""

    PUBLICATION = "publication"
    APPLICATION = "application"


@dataclass(frozen=True, slots=True)
class ReadPatentNumber:
    """Numéro de brevet lu dans un texte libre."""

    kind: PatentNumberKind
    value: str
    """Forme de `PatentNumber` : `FR3053353`, `WO2025050875`."""


_OFFICES = "WO|EP|FR|US|JP|CN|KR|DE|GB|ES|IT|CA|AU|BR|IN|RU|MX|IL|ZA|CH|AT|BE|NL|DK|SE|FI|NO|PL|PT"
"""Offices reconnus devant un numéro. Une autre paire de lettres devant des chiffres est une référence interne."""

_TOKEN_RE = re.compile(
    r"PCT/?[A-Z]{2}/?(?P<pct_year>\d{4})/?(?P<pct_number>\d{5,6})(?!\d)"
    r"|WO(?P<docdb_year>\d{4})[A-Z]{2}(?P<docdb_number>\d{5,6})(?!\d)"
    rf"|(?P<office>{_OFFICES})[\s.:/°N-]*(?P<number>\d[\d\s.,/]*\d)(?!\d)"
    r"|(?<![\dA-Z])(?P<bare>\d[\d\s.,/]*\d)(?!\d)"
)
"""Demande internationale écrite `PCT/FR2025/050875` ou `WO2022FR50459`, nombre précédé d'un office, ou nombre seul. Un nombre collé à une lettre est un code de type (`A1`) ou une référence interne."""

_US_GRANT_RE = re.compile(r"\d{1,2},\d{3},\d{3}")
"""Numéro de brevet américain délivré, écrit avec des virgules et sans office (`11,198,814`)."""

_EP_APPLICATION_RE = re.compile(r"(\d{8})\.\d")
"""Demande européenne suivie de son chiffre de contrôle (`21306403.3`)."""

_OTHER_OFFICE_MIN_DIGITS = 5
"""Nombre de chiffres minimal d'un numéro d'un office autre que WO, EP, FR et US."""


def _international_application(year: str, number: str) -> ReadPatentNumber:
    return ReadPatentNumber(PatentNumberKind.APPLICATION, f"WO{year}{int(number):06d}")


def _french(digits: str, year: int | None) -> ReadPatentNumber | None:
    """Lit un numéro français de sept chiffres.

    Un numéro de demande commence par l'année de dépôt sur deux chiffres. Un numéro de publication commence par 2 jusqu'en 2014, puis par 3. Un numéro commençant par 3, ou par une année postérieure à `year`, est une publication.
    """
    if len(digits) != 7:
        return None
    filed = 2000 + int(digits[:2])
    if digits[0] == "3" or (year is not None and filed > year + 1):
        return ReadPatentNumber(PatentNumberKind.PUBLICATION, f"FR{digits}")
    return ReadPatentNumber(PatentNumberKind.APPLICATION, f"FR{digits}")


def _bare(number: str, digits: str, year: int | None) -> ReadPatentNumber | None:
    if m := _EP_APPLICATION_RE.fullmatch(number):
        return ReadPatentNumber(PatentNumberKind.APPLICATION, f"EP{m.group(1)}")
    if _US_GRANT_RE.fullmatch(number):
        return ReadPatentNumber(PatentNumberKind.PUBLICATION, f"US{digits}")
    return _french(digits, year)


def _wo(number: str, digits: str, year: int | None) -> ReadPatentNumber | None:
    if len(digits) == 10:
        return ReadPatentNumber(PatentNumberKind.PUBLICATION, f"WO{digits}")
    return None


def _ep(number: str, digits: str, year: int | None) -> ReadPatentNumber | None:
    if m := _EP_APPLICATION_RE.fullmatch(number):
        return ReadPatentNumber(PatentNumberKind.APPLICATION, f"EP{m.group(1)}")
    if len(digits) == 7:
        return ReadPatentNumber(PatentNumberKind.PUBLICATION, f"EP{digits}")
    if len(digits) == 8:
        return ReadPatentNumber(PatentNumberKind.APPLICATION, f"EP{digits}")
    return None


def _fr(number: str, digits: str, year: int | None) -> ReadPatentNumber | None:
    if len(digits) == 10:
        # Demande internationale déposée en France, écrite sans `PCT/` (`FR2017050584`).
        return _international_application(digits[:4], digits[4:])
    if len(digits) == 9 and digits.startswith("20"):
        # Année sur quatre chiffres (`FR2024/04.864`).
        return ReadPatentNumber(PatentNumberKind.APPLICATION, f"FR{digits[2:]}")
    return _french(digits, year)


def _us(number: str, digits: str, year: int | None) -> ReadPatentNumber | None:
    if len(digits) == 11 and digits.startswith("20") and digits[4] == "0":
        # Publication de demande : l'année, puis le numéro sur six chiffres (`US20240211607` → `US2024211607`).
        return ReadPatentNumber(PatentNumberKind.PUBLICATION, f"US{digits[:4]}{digits[5:]}")
    if len(digits) in (7, 8, 10):
        return ReadPatentNumber(PatentNumberKind.PUBLICATION, f"US{digits}")
    return None


_READERS = {"WO": _wo, "EP": _ep, "FR": _fr, "US": _us}
"""Lecture d'un nombre précédé de l'office, pour les offices de forme connue."""


def _read(office: str | None, number: str, year: int | None) -> ReadPatentNumber | None:
    """Lit un nombre, précédé ou non de son office. Le nombre d'un autre office est une publication."""
    digits = re.sub(r"\D", "", number)
    if office is None:
        return _bare(number, digits, year)
    if reader := _READERS.get(office):
        return reader(number, digits, year)
    if len(digits) < _OTHER_OFFICE_MIN_DIGITS:
        return None
    return ReadPatentNumber(PatentNumberKind.PUBLICATION, f"{office}{digits}")


_DISCLOSURE_RE = re.compile(r"DI-?RV|D[ée]claration d.invention|SOLEAU|\bDSO\d", re.IGNORECASE)
"""Déclaration d'invention d'INRAE (`DI-RV-22-0027`, « Déclaration d'Invention et de Résultats Valorisables ») ou enveloppe Soleau (`DSO2021006565`)."""


def is_disclosure(number: str | None, title: str | None) -> bool:
    """Indique si un dépôt de type brevet désigne une déclaration d'invention ou une enveloppe Soleau, d'après son numéro ou son titre."""
    return bool(_DISCLOSURE_RE.search(f"{number or ''} {title or ''}"))


def read_patent_numbers(text: str | None, year: int | None = None) -> list[ReadPatentNumber]:
    """Renvoie les numéros de brevet de `text`, dans l'ordre, sans doublon.

    Args:
        year: année du document cité. Elle distingue une demande française d'une publication ancienne de même forme.
    """
    found: list[ReadPatentNumber] = []
    for m in _TOKEN_RE.finditer((text or "").upper()):
        if m.group("pct_year"):
            read = _international_application(m.group("pct_year"), m.group("pct_number"))
        elif m.group("docdb_year"):
            read = _international_application(m.group("docdb_year"), m.group("docdb_number"))
        elif m.group("office"):
            read = _read(m.group("office"), m.group("number"), year)
        else:
            read = _read(None, m.group("bare"), year)
        if read and PatentNumber.normalize(read.value) == read.value and read not in found:
            found.append(read)
    return found
