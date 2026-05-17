"""DTOs Subjects — contrats de retour des query services consommés par les routers FastAPI.

Déplacés depuis `interfaces/api/models/subjects.py` dans le cadre du chantier `CODE_typage-projections-strict` Phase 4 : les ports `application/ports/api/*_queries.py` renvoient directement ces DTOs (au lieu de `dict[str, Any]`), les adapters `infrastructure/queries/subjects.py` les instancient, et les routers les propagent sans `model_validate`.

`interfaces/api/models/subjects.py` reste comme module de re-export pour les imports historiques (`from interfaces.api.models import SubjectXxx`).
"""

from pydantic import BaseModel


class SubjectOntologyEntry(BaseModel):
    """Annotation d'un sujet par une ontologie donnée :
    - `codes` : codes intra-ontologie observés (ex 'info' pour HAL).
    - `level` : niveau hiérarchique (0=racine), null si non applicable.
    - `parent` : libellé du sujet parent dans la même ontologie, null si racine.
    """

    codes: list[str]
    level: int | None = None
    parent: str | None = None


class SubjectOut(BaseModel):
    """Sujet attaché à une publication, agrégé par `subject_id` sur les
    différentes sources qui l'ont annoté.

    `ontologies` : annotations multi-sources. Vide pour un libre.
    """

    id: int
    label: str
    language: str | None
    ontologies: dict[str, SubjectOntologyEntry]
    sources: list[str]  # publications sources qui ont annoté ce sujet


class SubjectListItem(BaseModel):
    """Sujet dans une liste paginée (page `/subjects`)."""

    id: int
    label: str
    language: str | None
    ontologies: dict[str, SubjectOntologyEntry]
    usage_count: int


class SubjectListResponse(BaseModel):
    items: list[SubjectListItem]
    total: int
    page: int
    per_page: int


class SubjectNeighborOut(BaseModel):
    """Voisin d'un sujet par co-occurrence."""

    id: int
    label: str
    ontologies: dict[str, SubjectOntologyEntry]
    usage_count: int
    cooccurrence_count: int


class SubjectDetailResponse(BaseModel):
    """Détail d'un sujet + ses voisins par co-occurrence (page graphe)."""

    subject: SubjectListItem
    neighbors: list[SubjectNeighborOut]


class SubjectFrequency(BaseModel):
    """Sujet avec fréquence locale (count des publis du contexte parent :
    labo ou personne). Utilisé pour les nuages de mots."""

    id: int
    label: str
    ontologies: dict[str, SubjectOntologyEntry]
    count: int
