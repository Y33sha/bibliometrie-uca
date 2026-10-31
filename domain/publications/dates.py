"""Date de publication d'un enregistrement source ou d'une publication, avec sa précision."""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


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

    @property
    def year(self) -> int:
        return self.value.year
