"""Nom d'un auteur tel qu'une source le donne sur une signature."""

from dataclasses import dataclass

from domain.errors import ValidationError
from domain.normalize import clean_raw_author_name, normalize_name_form
from domain.persons.name_matching import normalize_first_name, parse_raw_author_name


@dataclass(frozen=True, slots=True)
class SignatureName:
    """Nom d'auteur d'une signature (VO) : nom et prénom séparés, ou chaîne brute.

    La forme suit la source : Crossref, DataCite, WoS, HAL et theses.fr séparent nom et prénom, OpenAlex et ScanR donnent une chaîne. Les fabriques `from_parts` et `from_raw` nettoient les valeurs (`clean_raw_author_name`).
    """

    last_name: str | None = None
    first_name: str | None = None
    raw: str | None = None

    def __post_init__(self) -> None:
        if (self.last_name is None) == (self.raw is None):
            raise ValidationError("SignatureName : nom de famille ou chaîne brute, exclusivement")
        if self.first_name is not None and self.last_name is None:
            raise ValidationError("SignatureName : prénom sans nom de famille")

    @classmethod
    def from_parts(cls, last_name: str | None, first_name: str | None) -> "SignatureName | None":
        """Nom séparé par la source. Sans nom de famille, le prénom seul devient la chaîne brute. `None` sans aucun nom."""
        last = clean_raw_author_name(last_name or "").strip()
        first = clean_raw_author_name(first_name or "").strip()
        if not last:
            return cls.from_raw(first)
        return cls(last_name=last, first_name=first or None)

    @classmethod
    def from_raw(cls, raw: str | None) -> "SignatureName | None":
        """Chaîne brute. `None` pour une chaîne vide."""
        cleaned = clean_raw_author_name(raw or "").strip()
        return cls(raw=cleaned) if cleaned else None

    def split(self) -> tuple[str, str]:
        """(nom de famille, prénom) : ceux de la source, sinon le découpage de `parse_raw_author_name`."""
        if self.last_name is not None:
            return self.last_name, self.first_name or ""
        return parse_raw_author_name(self.raw)

    def normalized(self) -> tuple[str, str | None]:
        """(nom de famille, prénom) normalisés, initiales du prénom séparées (`normalize_first_name`). Prénom `None` quand il est vide."""
        last, first = self.split()
        return normalize_name_form(last), normalize_first_name(first) or None

    def display(self) -> str:
        """Forme « Prénom Nom », ou la chaîne brute."""
        if self.raw is not None:
            return self.raw
        return f"{self.first_name} {self.last_name}" if self.first_name else self.last_name or ""
