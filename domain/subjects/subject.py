"""Sujet d'un vocabulaire d'indexation, identifié par son code, et sujet donné par un enregistrement source."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from domain.identifiers import IdRef
from domain.normalize import normalize_text


class SubjectVocabulary(StrEnum):
    """Vocabulaire d'un sujet. Reflet du type PostgreSQL `subject_vocabulary`. La langue des libellés découle du vocabulaire."""

    OPENALEX = "openalex"
    """Classement OpenAlex : domain, field, subfield, topic. Libellés en anglais."""
    HAL_DOMAIN = "hal_domain"
    """Domaines du référentiel HAL. Libellés en français."""
    RAMEAU = "rameau"
    """Vedettes RAMEAU, codées par leur PPN. Libellés en français."""
    THESES_DISCIPLINE = "theses_discipline"
    """Disciplines des thèses de theses.fr, libellés libres en français."""


VOCABULARY_LABELS: dict[str, str] = {
    SubjectVocabulary.OPENALEX: "OpenAlex",
    SubjectVocabulary.HAL_DOMAIN: "Domaines HAL",
    SubjectVocabulary.RAMEAU: "RAMEAU",
    SubjectVocabulary.THESES_DISCIPLINE: "Disciplines de thèse",
}
"""Libellé d'affichage de chaque vocabulaire."""


@dataclass(frozen=True, slots=True)
class Subject:
    """Sujet d'un vocabulaire, avec la chaîne de ses ancêtres."""

    vocabulary: SubjectVocabulary
    code: str
    label: str
    parent: Subject | None = None
    """Sujet du niveau supérieur, du même vocabulaire."""

    @property
    def level(self) -> int:
        """Profondeur dans le vocabulaire : 1 pour une racine."""
        return 1 if self.parent is None else self.parent.level + 1

    def lineage(self) -> list[Subject]:
        """Renvoie la chaîne des ancêtres, de la racine au sujet compris."""
        return [*(self.parent.lineage() if self.parent else ()), self]


@dataclass(frozen=True, slots=True)
class SubjectLink:
    """Sujet donné par un enregistrement source."""

    subject: Subject
    score: float | None = None
    """Score OpenAlex du topic."""


def rameau_subject(ppn: str | None, label: str | None) -> Subject | None:
    """Renvoie la vedette RAMEAU de ce PPN. `None` si le PPN est invalide ou le libellé vide."""
    code = IdRef.normalize(ppn)
    label = (label or "").strip()
    return Subject(SubjectVocabulary.RAMEAU, code, label) if code and label else None


def theses_discipline_subject(label: str | None) -> Subject | None:
    """Renvoie la discipline de thèse de ce libellé, codée par son libellé normalisé. `None` pour un libellé vide."""
    label = (label or "").strip()
    code = normalize_text(label)
    return Subject(SubjectVocabulary.THESES_DISCIPLINE, code, label) if code else None
