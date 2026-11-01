"""Modèles de réponse : lectures sur les sujets.

Les écritures du référentiel appartiennent à la phase `subjects` (`pipeline/transformation/publications/subjects/subject_store.py`).

Un sujet de vocabulaire est une ligne de `subjects`. Les pages publiques regroupent les sujets de même libellé normalisé, tous vocabulaires confondus (`subject_labels`) : le libellé normalisé les identifie.

`SubjectFrequency` sert aussi les nuages de sujets des personnes, des laboratoires, des revues et des éditeurs.
"""

from dataclasses import dataclass
from typing import Literal

from application.ports.model import Model
from domain.subjects.subject import SubjectVocabulary
from infrastructure.read_models._common import FacetOption, PaginatedResponse

# Vocabulaire de tri de la liste des sujets : le champ, puis le sens.
SubjectSort = Literal["label_asc", "label_desc", "publications_asc", "publications_desc"]


@dataclass(frozen=True, slots=True)
class SubjectFilters:
    """Filtres de la liste des sujets."""

    search: str = ""
    """Terme cherché dans le libellé normalisé."""
    vocabularies: tuple[str, ...] = ()
    """Vocabulaires retenus : le sujet en a au moins un. Vide, tous les vocabulaires."""


class SubjectsFacetsResponse(Model):
    """Facettes de la liste des sujets. Le décompte d'un vocabulaire écarte le filtre des vocabulaires : il donne le nombre de sujets retenus si l'option est cochée."""

    vocabularies: list[FacetOption]


class SubjectOut(Model):
    """Sujet de vocabulaire attaché à une publication, une ligne par sujet toutes sources réunies."""

    id: int
    label: str
    label_normalized: str
    """Identifiant de la page du sujet."""
    vocabulary: SubjectVocabulary
    level: int
    """Profondeur dans le vocabulaire : 1 pour une racine."""
    sources: list[str]
    """Sources ayant fourni le sujet."""


class SubjectLabelRef(Model):
    """Lien vers la page d'un sujet."""

    label_normalized: str
    label: str


class SubjectListItem(SubjectLabelRef):
    """Sujet regroupé par libellé, avec ses vocabulaires et son nombre de publications."""

    vocabularies: list[SubjectVocabulary]
    usage_count: int


class SubjectListResponse(PaginatedResponse):
    items: list[SubjectListItem]


class SubjectChildOut(SubjectLabelRef):
    """Enfant d'un sujet de vocabulaire, avec son nombre de publications dans ce vocabulaire."""

    usage_count: int


class VocabularySubjectOut(Model):
    """Sujet de vocabulaire de même libellé normalisé, avec sa place dans l'arborescence."""

    vocabulary: SubjectVocabulary
    code: str
    level: int
    """Profondeur dans le vocabulaire : 1 pour une racine."""
    usage_count: int
    ancestors: list[SubjectLabelRef]
    """De la racine au parent."""
    children: list[SubjectChildOut]


class SubjectNeighborOut(SubjectLabelRef):
    """Voisin d'un sujet par co-occurrence."""

    usage_count: int
    cooccurrence_count: int


class SubjectNeighborLink(Model):
    """Co-occurrence entre deux voisins d'un sujet, `label_a` < `label_b` (libellés normalisés)."""

    label_a: str
    label_b: str
    cooccurrence_count: int


class SubjectDetailResponse(Model):
    """Détail d'un sujet : ses sujets de vocabulaire, ses voisins par co-occurrence et les co-occurrences entre ces voisins."""

    subject: SubjectListItem
    vocabulary_subjects: list[VocabularySubjectOut]
    neighbors: list[SubjectNeighborOut]
    neighbor_links: list[SubjectNeighborLink]


class SubjectFrequency(SubjectLabelRef):
    """Sujet et son nombre de publications au sein d'une personne, d'un laboratoire, d'une revue ou d'un éditeur, pour les sujets principaux de son tableau de bord."""

    count: int
