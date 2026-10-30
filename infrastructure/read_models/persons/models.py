"""Modèles de réponse : lectures sur les personnes."""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel

from domain.persons.identifiers import AttributionStatus
from domain.persons.person import PersonExclusion
from infrastructure.read_models._common import (
    FacetOption,
    PaginatedResponse,
    StructureRef,
    YesNoCount,
)

# Vocabulaire de tri : le champ, puis le sens. Les deux dénombrements sont triables, comme la fonction et le département.
PersonSort = Literal[
    "name_asc",
    "name_desc",
    "contributions_asc",
    "contributions_desc",
    "in_perimeter_contributions_asc",
    "in_perimeter_contributions_desc",
    "dept_asc",
    "dept_desc",
    "role_asc",
    "role_desc",
]


@dataclass(frozen=True, slots=True)
class PersonFilters:
    """Filtres des lectures de personnes : liste et facettes.

    Les `has_*` filtrent sur la présence ou l'absence, et `None` ne filtre pas.
    """

    search: str = ""
    departments: list[str] = field(default_factory=list)
    """Multi-valué : une option cochée s'ajoute aux autres."""
    roles: list[str] = field(default_factory=list)
    """Multi-valué : une option cochée s'ajoute aux autres."""
    has_orcid: bool | None = None
    has_idhal: bool | None = None
    has_idref: bool | None = None
    has_rh: bool | None = None
    has_pending_forms: bool | None = None
    """Au moins une forme de nom `pending`."""
    has_pending_identifiers: bool | None = None
    """Au moins un identifiant `pending`."""
    exclusions: list[PersonExclusion | None] = field(default_factory=list)
    """Motifs d'exclusion retenus, `None` désignant les personnes retenues ; vide, tout passe."""
    active: bool | None = None
    """Au moins une contribution ou une fiche RH. Une personne conservée pour ses seules décisions est inactive."""
    lab_id: int | None = None
    """Restreint la liste aux personnes du laboratoire, et leurs dénombrements à ce laboratoire."""


# ---------------------------------------------------------------------------
# Identifiants et formes de nom, communs à plusieurs réponses
# ---------------------------------------------------------------------------


class PersonIdentifierOut(BaseModel):
    """Identifiant (ORCID, idHAL, idRef) attaché à une personne."""

    id: int
    id_type: str
    id_value: str
    source: str
    status: AttributionStatus


class NameFormSummaryOut(BaseModel):
    """Forme de nom observée pour une personne, avec son état d'arbitrage."""

    name_form: str
    sources: list[str]
    status: Literal[
        AttributionStatus.PENDING, AttributionStatus.CONFIRMED, AttributionStatus.REJECTED
    ]
    shared_count: int
    publication_count: int


# ---------------------------------------------------------------------------
# Liste et recherche
# ---------------------------------------------------------------------------


class PersonSearchResult(BaseModel):
    """Résultat d'autocomplétion de `/api/persons/search`."""

    id: int
    last_name: str
    first_name: str
    department_name: str | None
    has_rh: bool


class PersonOut(BaseModel):
    """Ligne de `/api/persons`. Les dénombrements se restreignent au laboratoire avec `lab_id`."""

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None
    has_rh: bool
    exclusion: PersonExclusion | None
    contribution_count: int
    """Contributions où la personne tient le rôle d'auteur."""
    in_perimeter_contribution_count: int
    """Contributions d'auteur retenues dans le périmètre."""
    identifiers: list[PersonIdentifierOut]


class PersonListResponse(PaginatedResponse):
    persons: list[PersonOut]


# ---------------------------------------------------------------------------
# Facettes
# ---------------------------------------------------------------------------


class PersonsFacetsResponse(BaseModel):
    """Réponse de `/api/persons/facets`."""

    departments: list[FacetOption]
    roles: list[FacetOption]
    orcid: YesNoCount
    idhal: YesNoCount
    idref: YesNoCount
    rh: YesNoCount
    pending_forms: YesNoCount
    pending_identifiers: YesNoCount


# ---------------------------------------------------------------------------
# Détail d'une personne
# ---------------------------------------------------------------------------


class PersonProfileCore(BaseModel):
    """Bloc `person` de `/api/persons/{id}`."""

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None


class PersonProfileResponse(BaseModel):
    person: PersonProfileCore
    identifiers: list[PersonIdentifierOut]
    theses_count: int


class PersonThesis(BaseModel):
    id: int
    title: str
    publication_year: int | None
    doi: str | None
    author_name: str | None
    author_person_id: int | None
    structure_ids: list[int]


class PersonThesesSection(BaseModel):
    role: str
    label: str
    theses: list[PersonThesis]


class PersonThesesResponse(BaseModel):
    sections: list[PersonThesesSection]
    total: int
    structures: dict[int, StructureRef]


class PersonAddressStruct(BaseModel):
    id: int
    acronym: str | None
    name: str


class PersonAddressOut(BaseModel):
    id: int
    raw_text: str
    publication_count: int
    """Nombre de publications de la personne dont une contribution source porte l'adresse."""
    structures: list[PersonAddressStruct] | None


class PersonAddressesResponse(PaginatedResponse):
    addresses: list[PersonAddressOut]


class PersonAddressStructureCount(PersonAddressStruct):
    publications: int
    """Nombre de publications de la personne dont une adresse est rattachée à la structure."""


class PersonAddressSummary(BaseModel):
    """Structures reconnues dans les adresses de la personne, comptées en publications."""

    first_year: int | None
    """Année de la plus ancienne publication de la personne."""
    last_year: int | None
    """Année de la plus récente publication de la personne."""
    publications: int
    """Nombre de publications de la personne."""
    publications_with_address: int
    """Nombre de publications de la personne dont une contribution source porte une adresse."""
    structures: list[PersonAddressStructureCount]


# ---------------------------------------------------------------------------
# Administration : formes de nom (`name_form_contributions`)
# ---------------------------------------------------------------------------


class NameFormContributionRef(BaseModel):
    source: str
    source_contribution_id: int
    publication_id: int
    title: str
    publication_year: int | None
    doi: str | None


class OtherPersonOut(BaseModel):
    person_id: int
    first_name: str
    last_name: str
    department_name: str | None
    has_rh: bool


class NameFormContributionsResponse(BaseModel):
    contributions: list[NameFormContributionRef]
    other_persons: list[OtherPersonOut]


# ---------------------------------------------------------------------------
# Triage : formes de nom ambiguës
# ---------------------------------------------------------------------------


class AmbiguousFormPersonOut(BaseModel):
    person_id: int
    first_name: str
    last_name: str
    status: Literal[
        AttributionStatus.PENDING, AttributionStatus.CONFIRMED, AttributionStatus.REJECTED
    ]
    canonical: bool
    """Forme dérivée du nom de la personne : confirmée d'office, statut non modifiable."""
    has_rh: bool
    compatible: bool
    """Nom de la personne compatible avec la forme (mêmes mots) : homonyme ou doublon si vrai, erreur d'attribution probable si faux."""


class AmbiguousNameFormOut(BaseModel):
    name_form: str
    persons: list[AmbiguousFormPersonOut]


class AmbiguousNameFormsResponse(PaginatedResponse):
    forms: list[AmbiguousNameFormOut]


class CurationPersonOut(BaseModel):
    """Fiche personne allégée, commune aux files de triage (conflits d'identifiant, doublons par nom)."""

    person_id: int
    first_name: str
    last_name: str
    has_rh: bool
    contribution_count: int
    """Contributions où la personne tient le rôle d'auteur, même mesure que la liste des personnes."""
    labs: list[str]


class IdentifierRef(BaseModel):
    id_type: str
    id_value: str


class IdentifierConflictPairOut(BaseModel):
    """Deux personnes distinctes à même valeur brute d'identifiant (ORCID, IdRef, hal_person_id, idHAL) : doublon probable ou erreur d'attribution."""

    person_a: CurationPersonOut
    person_b: CurationPersonOut
    shared_identifiers: list[IdentifierRef]


class IdentifierConflictsResponse(PaginatedResponse):
    pairs: list[IdentifierConflictPairOut]


class OverlapCountsOut(BaseModel):
    """Recouvrements de réseau entre deux personnes d'une paire candidate par nom."""

    coauthors: int
    shared_publications: int
    labs: int
    serials: int


class NameDuplicatePairOut(BaseModel):
    """Deux personnes aux noms compatibles, avec leurs recouvrements de réseau. Un réseau commun (co-auteurs, publications co-signées) indique un doublon ; des réseaux disjoints, un homonyme."""

    person_a: CurationPersonOut
    person_b: CurationPersonOut
    overlaps: OverlapCountsOut


class NameDuplicatesResponse(PaginatedResponse):
    pairs: list[NameDuplicatePairOut]


class DistinctPersonOut(BaseModel):
    """Personne déclarée distincte d'une autre."""

    person_id: int
    first_name: str
    last_name: str
    has_rh: bool


class SharingPersonOut(BaseModel):
    """Personne partageant au moins une forme de nom avec une autre, candidate à l'absorption."""

    person_id: int
    first_name: str
    last_name: str
    has_rh: bool
    shared_forms: list[str]
