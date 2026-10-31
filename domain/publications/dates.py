"""Date de publication d'un enregistrement source ou d'une publication, avec sa précision, et lecture des dates des sources."""

import calendar
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from domain.types import JsonValue, as_int, as_mapping, as_sequence


class DatePrecision(StrEnum):
    """Précision d'une date de publication. Reflet du type PostgreSQL `date_precision`."""

    YEAR = "year"
    MONTH = "month"
    DAY = "day"


@dataclass(frozen=True, slots=True)
class PublicationDate:
    """Date de publication. Une date à l'année tombe le 1er janvier, une date au mois le 1er du mois."""

    value: date
    precision: DatePrecision

    @classmethod
    def of_year(cls, year: int) -> PublicationDate:
        """Renvoie la date à l'année `year`."""
        return cls(date(year, 1, 1), DatePrecision.YEAR)

    @classmethod
    def stored(cls, value: date | None, precision: str | None) -> PublicationDate | None:
        """Renvoie la date lue dans les colonnes `publication_date` et `publication_date_precision`, ou `None` sans date."""
        if value is None or precision is None:
            return None
        return cls(value, DatePrecision(precision))

    @property
    def year(self) -> int:
        return self.value.year

    def without_placeholder_day(self) -> PublicationDate:
        """Renvoie le 1er janvier à l'année, le 1er d'un autre mois au mois. OpenAlex et ScanR datent ainsi au jour une année ou un mois seuls."""
        if self.precision is not DatePrecision.DAY or self.value.day != 1:
            return self
        if self.value.month == 1:
            return PublicationDate(self.value, DatePrecision.YEAR)
        return PublicationDate(self.value, DatePrecision.MONTH)


_RANK = {DatePrecision.YEAR: 0, DatePrecision.MONTH: 1, DatePrecision.DAY: 2}


def _agrees(coarse: PublicationDate, fine: PublicationDate) -> bool:
    """Vrai si `fine` a l'année de `coarse`, et son mois quand `coarse` est au mois ou au jour."""
    if fine.value.year != coarse.value.year:
        return False
    return coarse.precision is DatePrecision.YEAR or fine.value.month == coarse.value.month


def arbitrate_publication_date(dates: Sequence[PublicationDate]) -> PublicationDate | None:
    """Renvoie la date de la première source de `dates`, précisée par les suivantes quand elles concordent : « 2024 » puis « 15 octobre 2024 » donnent le 15 octobre 2024, « 2024 » puis « 15 octobre 2023 » donnent 2024.

    Args:
        dates: dates des enregistrements sources, de la source prioritaire à la moins prioritaire.
    """
    if not dates:
        return None
    best = dates[0]
    for candidate in dates[1:]:
        if _RANK[candidate.precision] > _RANK[best.precision] and _agrees(best, candidate):
            best = candidate
    return best


_MIN_YEAR, _MAX_YEAR = 1000, 2100


def date_from_parts(
    year: int | None, month: int | None = None, day: int | None = None
) -> PublicationDate | None:
    """Renvoie la date de ces composantes, à la précision de la dernière composante valide ; `None` sans année plausible."""
    if year is None or not _MIN_YEAR <= year <= _MAX_YEAR:
        return None
    if month is None or not 1 <= month <= 12:
        return PublicationDate(date(year, 1, 1), DatePrecision.YEAR)
    if day is None or not 1 <= day <= calendar.monthrange(year, month)[1]:
        return PublicationDate(date(year, month, 1), DatePrecision.MONTH)
    return PublicationDate(date(year, month, day), DatePrecision.DAY)


_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:$|T|\s)")


def parse_iso_date(raw: str | None) -> PublicationDate | None:
    """Lit une date `AAAA`, `AAAA-MM` ou `AAAA-MM-JJ`, suivie ou non d'une heure."""
    m = _ISO.match((raw or "").strip())
    if not m:
        return None
    return date_from_parts(*(int(g) if g else None for g in m.groups()))


def parse_date_parts(value: JsonValue) -> PublicationDate | None:
    """Lit une date Crossref : `{"date-parts": [[année, mois, jour]]}`, mois et jour facultatifs."""
    parts = as_sequence(as_mapping(value).get("date-parts"))
    first = as_sequence(parts[0]) if parts else []
    year, month, day = ([as_int(p) for p in first] + [None, None, None])[:3]
    return date_from_parts(year, month, day)


_MONTHS = {m.upper(): i for i, m in enumerate(calendar.month_abbr) if m}
# Date WoS : mois abrégé facultatif (« OCT », « OCT-NOV », « SPR »), jour facultatif, année facultative.
_WOS = re.compile(r"^(?:([A-Z]{3})[A-Z-]*)?\s*(\d{1,2})?(?:-\d{1,2})?\s*(\d{4})?$")
# Date WoS année en tête : « 2026 AUG 31 ».
_WOS_YEAR_FIRST = re.compile(r"^(\d{4})\s+([A-Z]{3})\s*(\d{1,2})?$")


def parse_wos_date(raw: str | None, year: int | None = None) -> PublicationDate | None:
    """Lit une date WoS en mois abrégé (« OCT 10 2023 », « DEC 2024 », « 2025 », « 2026 AUG 31 ») ; `year` à défaut d'année dans le texte. Une saison (« SPR ») donne l'année."""
    cleaned = (raw or "").strip().upper()
    if m := _WOS_YEAR_FIRST.match(cleaned):
        text_year, month_name, day = m.groups()
    elif m := _WOS.match(cleaned):
        month_name, day, text_year = m.groups()
    else:
        return None
    return date_from_parts(
        int(text_year) if text_year else year,
        _MONTHS.get(month_name or ""),
        int(day) if day else None,
    )
