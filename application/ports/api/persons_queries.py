"""Port : lectures sur les personnes (consommé par le router persons).

Implémenté par `infrastructure.queries.api.persons.PgPersonsQueries`. Les modèles Pydantic que ces lectures rendent sont co-localisés avec le `Protocol` : leur contrat appartient au port.

Les dataclasses `DirectoryFilters`, `ListFilters` et `FacetFilters` font ici référence ; l'infrastructure les importe pour typer ses signatures (règle 3 de `docs/architecture/01-vue-d-ensemble.md`).
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel

from application.ports.api._common import (
    DashboardOa,
    FacetValueCount,
    PaginatedResponse,
    PubYearCount,
    StructureRef,
    YesNoCount,
)
from application.ports.api.subjects_queries import SubjectFrequency

# Vocabulaire de tri : le champ, puis le sens. Les trois dénombrements sont triables, comme
# la fonction et le département.
PersonSort = Literal[
    "name_asc",
    "name_desc",
    "signatures_asc",
    "signatures_desc",
    "signatures_as_author_asc",
    "signatures_as_author_desc",
    "in_perimeter_signatures_asc",
    "in_perimeter_signatures_desc",
    "dept_asc",
    "dept_desc",
    "role_asc",
    "role_desc",
]


@dataclass(frozen=True, slots=True)
class PersonFilters:
    """Filtres des lectures de personnes — liste et facettes.

    `departments` et `roles` sont multi-valués : une option cochée s'ajoute aux autres. Les `has_*` filtrent sur la présence ou l'absence, et `None` ne filtre pas — y compris `rejected`, qui laisse alors passer les personnes écartées par la curation comme les autres.

    `lab_id` n'est pas un filtre mais un scope : il restreint aux personnes du laboratoire et y restreint aussi leurs dénombrements.
    """

    search: str = ""
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: bool | None = None
    has_idhal: bool | None = None
    has_idref: bool | None = None
    has_rh: bool | None = None
    # « À confirmer » : personnes portant ≥1 forme de nom / identifiant `pending`.
    has_pending_forms: bool | None = None
    has_pending_identifiers: bool | None = None
    rejected: bool | None = None
    lab_id: int | None = None


# ---------------------------------------------------------------------------
# DTOs Identifiants + formes de noms (réutilisés dans plusieurs réponses)
# ---------------------------------------------------------------------------


class PersonIdentifierOut(BaseModel):
    """Identifiant (ORCID, idHAL, idRef) attaché à une personne."""

    id: int
    id_type: str
    id_value: str
    source: str
    status: Literal["pending", "confirmed", "rejected", "authenticated"]


class NameFormSummaryOut(BaseModel):
    """Forme de nom observée pour une personne, avec son état d'arbitrage.

    Servie par personne, non dans la liste : seule la fiche d'une personne l'affiche.
    """

    name_form: str
    sources: list[str]
    ambiguous: bool
    status: Literal["pending", "confirmed", "rejected"]
    shared_count: int
    pub_count: int


# ---------------------------------------------------------------------------
# DTOs Liste / recherche
# ---------------------------------------------------------------------------


class PersonSearchResult(BaseModel):
    """Résultat d'autocomplete `/api/persons/search`."""

    id: int
    last_name: str
    first_name: str
    department_name: str | None
    has_rh: bool


class PersonOut(BaseModel):
    """Ligne de `/api/persons`.

    Les trois dénombrements comptent la même chose sous des conditions de plus en plus étroites, et se restreignent tous au laboratoire sous scope `lab_id`.
    """

    id: int
    last_name: str
    first_name: str
    role_title: str | None
    department_name: str | None
    start_date: date | None
    end_date: date | None
    has_rh: bool
    rejected: bool
    signature_count: int
    """Signatures de la personne, tous rôles — auteur, mais aussi jury ou rapporteur d'une thèse."""
    signature_count_as_author: int
    """Celles de ces signatures où la personne tient le rôle d'auteur."""
    in_perimeter_signature_count: int
    """Celles de ces signatures que le périmètre retient."""
    identifiers: list[PersonIdentifierOut]


class PersonListResponse(PaginatedResponse):
    persons: list[PersonOut]


# ---------------------------------------------------------------------------
# DTOs Facettes / référentiels / stats
# ---------------------------------------------------------------------------


class PersonsFacetsResponse(BaseModel):
    """Réponse de `/api/persons/facets`."""

    departments: list[FacetValueCount]
    roles: list[FacetValueCount]
    orcid: YesNoCount
    idhal: YesNoCount
    idref: YesNoCount
    rh: YesNoCount
    pending_forms: YesNoCount
    pending_identifiers: YesNoCount


class PersonsStatsResponse(BaseModel):
    total_persons: int
    linked_persons: int
    linked_authors: int
    departments: int


# ---------------------------------------------------------------------------
# DTOs Détail d'une personne
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


class PersonProfileAuthor(BaseModel):
    """Auteur source dans `/api/persons/{id}` (vue publique enrichie)."""

    id: int
    source: str
    full_name: str | None
    orcid: str | None
    idhal: str | None
    hal_person_id: int | None = None
    openalex_id: str | None
    in_perimeter_signature_count: int


class PersonProfileResponse(BaseModel):
    person: PersonProfileCore
    identifiers: list[PersonIdentifierOut]
    authors: list[PersonProfileAuthor]
    theses_count: int


class PersonThesis(BaseModel):
    id: int
    title: str
    pub_year: int | None
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
    structures: list[PersonAddressStruct] | None


class PersonAddressesResponse(PaginatedResponse):
    addresses: list[PersonAddressOut]


class PersonDashboardResponse(BaseModel):
    pubs_by_year: list[PubYearCount]
    oa: DashboardOa


# ---------------------------------------------------------------------------
# DTOs Admin : name forms (utilisés par `name_form_authorships`)
# ---------------------------------------------------------------------------


class NameFormAuthorshipRef(BaseModel):
    source: str
    source_authorship_id: int
    pub_id: int
    title: str
    pub_year: int | None
    doi: str | None


class OtherPersonOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    department_name: str | None
    has_rh: bool


class NameFormAuthorshipsResponse(BaseModel):
    authorships: list[NameFormAuthorshipRef]
    other_persons: list[OtherPersonOut]


# ---------------------------------------------------------------------------
# DTOs Triage : formes de nom ambiguës
# ---------------------------------------------------------------------------


class AmbiguousFormPersonOut(BaseModel):
    person_id: int
    first_name: str
    last_name: str
    status: Literal["pending", "confirmed", "rejected"]
    has_rh: bool
    # Nom canonique compatible (par tokens) avec la forme : homonyme/doublon si
    # vrai, erreur d'attribution probable si faux.
    compatible: bool


class AmbiguousNameFormOut(BaseModel):
    name_form: str
    persons: list[AmbiguousFormPersonOut]


class AmbiguousNameFormsResponse(PaginatedResponse):
    forms: list[AmbiguousNameFormOut]


class IdentifierConflictPersonOut(BaseModel):
    """Personne d'une paire en conflit d'identifiant, vue allégée (le détail complet est dans le drawer)."""

    person_id: int
    first_name: str
    last_name: str
    has_rh: bool
    signature_count: int
    """Signatures de la personne, tous rôles — même mesure que la liste de curation."""
    labs: list[str]


class SharedIdentifierOut(BaseModel):
    id_type: str
    id_value: str


class IdentifierConflictPairOut(BaseModel):
    """Deux personnes distinctes portant la même valeur brute d'identifiant (ORCID / IdRef / hal_person_id / idHAL) : doublon probable (mêmes nom/réseau) ou erreur d'attribution."""

    person_a: IdentifierConflictPersonOut
    person_b: IdentifierConflictPersonOut
    shared_identifiers: list[SharedIdentifierOut]


class IdentifierConflictsResponse(PaginatedResponse):
    pairs: list[IdentifierConflictPairOut]


class AnchorOccurrenceOut(BaseModel):
    """Signature légitime (nom compatible avec une forme confirmée) de la personne."""

    source: str
    raw_author_name: str


class IntruderOccurrenceOut(BaseModel):
    """Signature intruse : nom incompatible avec les formes confirmées de la personne. `name_form` est la forme à rejeter pour détacher la signature ; `identifiers` expose l'identifiant fautif."""

    source: str
    raw_author_name: str
    name_form: str
    identifiers: list[SharedIdentifierOut]


class DetachableIntruderGroupOut(BaseModel):
    """Une personne rattachée à ≥2 signatures d'une même publication, avec ancre(s) et intrus."""

    source_publication_id: int
    publication_id: int | None
    pub_title: str | None
    pub_year: int | None
    person: IdentifierConflictPersonOut
    anchors: list[AnchorOccurrenceOut]
    intruders: list[IntruderOccurrenceOut]


class DetachableIntrudersResponse(PaginatedResponse):
    groups: list[DetachableIntruderGroupOut]


class OverlapCountsOut(BaseModel):
    """Recouvrements de réseau entre deux personnes d'une paire candidate par nom."""

    coauthors: int
    shared_pubs: int
    labs: int
    journals: int


class NameDuplicatePairOut(BaseModel):
    """Deux personnes aux noms compatibles, avec leurs recouvrements de réseau. Un réseau commun (co-auteurs, publications co-signées) signe un doublon ; des réseaux disjoints, un homonyme."""

    person_a: IdentifierConflictPersonOut
    person_b: IdentifierConflictPersonOut
    overlaps: OverlapCountsOut


class NameDuplicatesResponse(PaginatedResponse):
    pairs: list[NameDuplicatePairOut]


class SharingPersonOut(BaseModel):
    """Personne partageant ≥1 forme de nom avec une autre (candidate à l'absorption)."""

    id: int
    first_name: str
    last_name: str
    has_rh: bool
    shared_forms: list[str]


class PersonsQueries(Protocol):
    """Lectures sync pour /api/persons/* + endpoints admin associés."""

    # ── Liste / recherche ──────────────────────────────────────────

    def search_persons(self, *, search: str, limit: int) -> list[PersonSearchResult]: ...

    def list_persons(
        self, *, filters: PersonFilters, page: int, per_page: int, sort: PersonSort
    ) -> PersonListResponse: ...

    def person_admin(self, person_id: int) -> PersonOut | None: ...

    # ── Facettes / listes de référence / stats ─────────────────────

    def persons_facets(self, *, filters: PersonFilters) -> PersonsFacetsResponse: ...

    def persons_stats(self) -> PersonsStatsResponse: ...

    def person_name_forms(self, person_id: int) -> list[NameFormSummaryOut]: ...

    # ── Détail d'une personne ──────────────────────────────────────

    def person_profile(self, person_id: int) -> PersonProfileResponse | None: ...

    def person_theses(self, person_id: int) -> PersonThesesResponse: ...

    def person_addresses(
        self, person_id: int, *, page: int, per_page: int
    ) -> PersonAddressesResponse: ...

    def person_dashboard(self, person_id: int) -> PersonDashboardResponse: ...

    def person_subjects(self, person_id: int, *, limit: int) -> list[SubjectFrequency]: ...

    # ── Admin : name forms ─────────────────────────────────────────

    def name_form_authorships(
        self, person_id: int, name_form: str
    ) -> NameFormAuthorshipsResponse: ...

    def ambiguous_name_forms_count(self) -> int: ...

    def ambiguous_name_forms(self, *, page: int, per_page: int) -> AmbiguousNameFormsResponse: ...

    def identifier_conflicts_count(self) -> int: ...

    def identifier_conflicts(self, *, page: int, per_page: int) -> IdentifierConflictsResponse: ...

    def detachable_intruders_count(self) -> int: ...

    def detachable_intruders(self, *, page: int, per_page: int) -> DetachableIntrudersResponse: ...

    def name_duplicates_count(self) -> int: ...

    def name_duplicates(self, *, page: int, per_page: int) -> NameDuplicatesResponse: ...

    def persons_sharing_name_form(self, person_id: int) -> list[SharingPersonOut]: ...
