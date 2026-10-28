"""Nom d'un auteur tel qu'une source le donne sur une contribution source."""

import re
from dataclasses import dataclass

from domain.errors import ValidationError
from domain.normalize import clean_raw_author_name, normalize_text
from domain.persons.name_matching import (
    family_name_splits,
    normalize_first_name,
    orient_initials,
    parse_raw_author_name,
)

# Mot qu'une source écrit à la place d'un nom absent : code DataCite de valeur inconnue (« (:unap) », « :unkn »), « None », « null ».
_PLACEHOLDER_RE = re.compile(
    r"\(?:(?:unac|unal|unap|unas|unav|unkn|none|null|tba)\)?|none|null", re.I
)


def is_placeholder_name(name: str) -> bool:
    """Le nom est fait seulement de mots qui tiennent lieu de nom absent (« (:Unap) », « None, None »). Un nom réel qui contient l'un de ces mots (« Paolo None ») n'en est pas un."""
    words = [w for w in re.split(r"[\s,]+", name) if w]
    return bool(words) and all(_PLACEHOLDER_RE.fullmatch(w) for w in words)


@dataclass(frozen=True, slots=True)
class ContributorName:
    """Nom d'auteur d'une contribution source (VO) : nom et prénom séparés, ou chaîne brute.

    La forme suit la source : Crossref, DataCite, WoS, HAL et theses.fr séparent nom et prénom, OpenAlex et ScanR donnent une chaîne. Les fabriques `from_parts` et `from_raw` nettoient les valeurs (`clean_raw_author_name`).
    """

    last_name: str | None = None
    first_name: str | None = None
    raw: str | None = None

    def __post_init__(self) -> None:
        if (self.last_name is None) == (self.raw is None):
            raise ValidationError("ContributorName : nom de famille ou chaîne brute, exclusivement")
        if self.first_name is not None and self.last_name is None:
            raise ValidationError("ContributorName : prénom sans nom de famille")

    @property
    def split_by_source(self) -> bool:
        """Vrai quand la source sépare nom et prénom, faux pour une chaîne brute découpée par le parseur."""
        return self.raw is None

    @classmethod
    def from_parts(cls, last_name: str | None, first_name: str | None) -> ContributorName | None:
        """Nom séparé par la source. Sans nom de famille, le prénom seul devient la chaîne brute. `None` sans aucun nom, ou pour un nom absent (`is_placeholder_name`)."""
        last = clean_raw_author_name(last_name or "").strip()
        first = clean_raw_author_name(first_name or "").strip()
        if is_placeholder_name(f"{last} {first}"):
            return None
        if not last:
            return cls.from_raw(first)
        return cls(last_name=last, first_name=first or None)

    @classmethod
    def from_raw(cls, raw: str | None) -> ContributorName | None:
        """Chaîne brute. `None` pour une chaîne vide ou un nom absent (`is_placeholder_name`)."""
        cleaned = clean_raw_author_name(raw or "").strip()
        return cls(raw=cleaned) if cleaned and not is_placeholder_name(cleaned) else None

    @classmethod
    def from_columns(
        cls, raw: str | None, last_name: str | None, first_name: str | None
    ) -> ContributorName:
        """Nom stocké d'une contribution source (`raw_author_name`, `raw_last_name`, `raw_first_name`), déjà nettoyé."""
        if last_name is not None:
            return cls(last_name=last_name, first_name=first_name)
        return cls(raw=raw)

    def split(self) -> tuple[str, str]:
        """(nom de famille, prénom) : ceux de la source, sinon le découpage de `parse_raw_author_name`. Un nom de la source réduit à des initiales passe en prénom (`orient_initials`)."""
        if self.last_name is not None:
            return orient_initials(self.last_name, self.first_name or "")
        return parse_raw_author_name(self.raw)

    def splits(self) -> list[tuple[str, str]]:
        """Découpages (nom de famille, prénom) possibles : celui de la source, sinon ceux de `family_name_splits`."""
        if self.last_name is not None:
            return [self.split()]
        return family_name_splits(self.raw)

    def first_name_for(self, last_name: str) -> str | None:
        """Prénom d'un découpage dont le nom de famille est `last_name`, `None` sinon."""
        target = normalize_text(last_name)
        for last, first in self.splits():
            if normalize_text(last) == target:
                return first
        return None

    def normalized(self) -> tuple[str, str | None]:
        """(nom de famille, prénom) normalisés, initiales du prénom séparées (`normalize_first_name`). Prénom `None` quand il est vide."""
        last, first = self.split()
        return normalize_text(last), normalize_first_name(first) or None

    def display(self) -> str:
        """Forme « Prénom Nom », ou la chaîne brute."""
        if self.raw is not None:
            return self.raw
        return f"{self.first_name} {self.last_name}" if self.first_name else self.last_name or ""
