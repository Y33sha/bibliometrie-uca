"""Query services de lecture autour des personnes (router persons).

Le package est organisé par thème :
- `list` : `persons_directory`, `search_persons`, `list_persons`
- `facets` : `persons_facets`, `list_departments`, `list_roles`, `persons_stats`
- `detail` : `person_profile`, `person_theses`, `person_addresses`,
  `person_dashboard`, `person_subjects`
- `admin` : `person_exists`, orphan authorships, name-form authorships

L'adapter d'écriture pipeline (`pipeline.persons_create`) vit côté
`infrastructure/queries/pipeline/`.

`PgPersonsQueries` agrège l'ensemble des fonctions de lecture + admin
sous le port `application.ports.api.persons_queries.PersonsQueries`. Les
fonctions libres retournent des dicts (réutilisables hors API) ; la
conversion vers les DTOs Pydantic est faite ici à la sortie de l'adapter.
"""

# Annotations différées : sinon `list[int]` est résolu comme le sous-module
# `.list` (le `from .list import …` ci-dessous l'attache au package, et le
# namespace global du __init__ shadow le builtin `list`).
from __future__ import annotations

from sqlalchemy import Connection

from application.ports.api.persons_queries import (
    AmbiguousNameFormsResponse,
    DepartmentCount,
    DetachableIntrudersResponse,
    DirectoryFilters,
    FacetFilters,
    IdentifierConflictsResponse,
    ListFilters,
    NameFormAuthorshipsResponse,
    OrphanAuthorshipsResponse,
    OrphanCountResponse,
    PersonAddressesResponse,
    PersonDashboardResponse,
    PersonDirectoryResponse,
    PersonListResponse,
    PersonOut,
    PersonProfileResponse,
    PersonSearchResult,
    PersonsFacetsResponse,
    PersonsQueries,
    PersonsStatsResponse,
    PersonThesesResponse,
    RoleCount,
    SharingPersonOut,
)
from application.ports.api.subjects_queries import SubjectFrequency
from infrastructure.queries.api.persons.admin import (
    ambiguous_name_forms as _ambiguous_name_forms,
    ambiguous_name_forms_count as _ambiguous_name_forms_count,
    detachable_intruders as _detachable_intruders,
    detachable_intruders_count as _detachable_intruders_count,
    identifier_conflicts as _identifier_conflicts,
    identifier_conflicts_count as _identifier_conflicts_count,
    list_orphan_authorships as _list_orphan_authorships,
    name_form_authorships as _name_form_authorships,
    orphan_authorships_count as _orphan_authorships_count,
    person_exists as _person_exists,
    persons_sharing_name_form as _persons_sharing_name_form,
)
from infrastructure.queries.api.persons.detail import (
    person_addresses as _person_addresses,
    person_dashboard as _person_dashboard,
    person_profile as _person_profile,
    person_subjects as _person_subjects,
    person_theses as _person_theses,
)
from infrastructure.queries.api.persons.facets import (
    list_departments as _list_departments,
    list_roles as _list_roles,
    persons_facets as _persons_facets,
    persons_stats as _persons_stats,
)
from infrastructure.queries.api.persons.list import (
    list_persons as _list_persons,
    person_admin as _person_admin,
    persons_directory as _persons_directory,
    search_persons as _search_persons,
)


class PgPersonsQueries(PersonsQueries):
    """Adapter SA pour `application.ports.api.persons_queries.PersonsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Annuaire / recherche / liste admin ─────────────────────────

    def persons_directory(
        self, *, filters: DirectoryFilters, page: int, per_page: int, sort: str
    ) -> PersonDirectoryResponse:
        return PersonDirectoryResponse.model_validate(
            _persons_directory(self._conn, filters=filters, page=page, per_page=per_page, sort=sort)
        )

    def search_persons(self, *, q: str, limit: int) -> list[PersonSearchResult]:
        return [
            PersonSearchResult.model_validate(r)
            for r in _search_persons(self._conn, q=q, limit=limit)
        ]

    def list_persons(
        self, *, filters: ListFilters, page: int, per_page: int, sort: str
    ) -> PersonListResponse:
        return PersonListResponse.model_validate(
            _list_persons(self._conn, filters=filters, page=page, per_page=per_page, sort=sort)
        )

    def person_admin(self, person_id: int) -> PersonOut | None:
        row = _person_admin(self._conn, person_id)
        return PersonOut.model_validate(row) if row is not None else None

    # ── Facettes / listes de référence / stats ─────────────────────

    def persons_facets(self, *, filters: FacetFilters) -> PersonsFacetsResponse:
        return PersonsFacetsResponse.model_validate(_persons_facets(self._conn, filters=filters))

    def list_departments(self) -> list[DepartmentCount]:
        return [DepartmentCount.model_validate(r) for r in _list_departments(self._conn)]

    def list_roles(self) -> list[RoleCount]:
        return [RoleCount.model_validate(r) for r in _list_roles(self._conn)]

    def persons_stats(self) -> PersonsStatsResponse:
        return PersonsStatsResponse.model_validate(_persons_stats(self._conn))

    # ── Détail d'une personne ──────────────────────────────────────

    def person_profile(self, person_id: int) -> PersonProfileResponse | None:
        data = _person_profile(self._conn, person_id)
        if data is None:
            return None
        return PersonProfileResponse.model_validate(data)

    def person_theses(self, person_id: int) -> PersonThesesResponse:
        return PersonThesesResponse.model_validate(_person_theses(self._conn, person_id))

    def person_addresses(
        self, person_id: int, *, page: int, per_page: int
    ) -> PersonAddressesResponse:
        return PersonAddressesResponse.model_validate(
            _person_addresses(self._conn, person_id, page=page, per_page=per_page)
        )

    def person_dashboard(self, person_id: int) -> PersonDashboardResponse:
        return PersonDashboardResponse.model_validate(_person_dashboard(self._conn, person_id))

    def person_subjects(self, person_id: int, *, limit: int) -> list[SubjectFrequency]:
        return [
            SubjectFrequency.model_validate(r)
            for r in _person_subjects(self._conn, person_id, limit=limit)
        ]

    # ── Admin : existence, orphan authorships, name forms ──────────

    def person_exists(self, person_id: int) -> bool:
        return _person_exists(self._conn, person_id)

    def orphan_authorships_count(self) -> OrphanCountResponse:
        return OrphanCountResponse.model_validate(_orphan_authorships_count(self._conn))

    def list_orphan_authorships(
        self, *, search: str, page: int, per_page: int
    ) -> OrphanAuthorshipsResponse:
        return OrphanAuthorshipsResponse.model_validate(
            _list_orphan_authorships(self._conn, search=search, page=page, per_page=per_page)
        )

    def name_form_authorships(self, person_id: int, name_form: str) -> NameFormAuthorshipsResponse:
        return NameFormAuthorshipsResponse.model_validate(
            _name_form_authorships(self._conn, person_id, name_form)
        )

    def ambiguous_name_forms_count(self) -> int:
        return _ambiguous_name_forms_count(self._conn)

    def ambiguous_name_forms(self, *, page: int, per_page: int) -> AmbiguousNameFormsResponse:
        return AmbiguousNameFormsResponse.model_validate(
            _ambiguous_name_forms(self._conn, page=page, per_page=per_page)
        )

    def identifier_conflicts_count(self) -> int:
        return _identifier_conflicts_count(self._conn)

    def identifier_conflicts(self, *, page: int, per_page: int) -> IdentifierConflictsResponse:
        return IdentifierConflictsResponse.model_validate(
            _identifier_conflicts(self._conn, page=page, per_page=per_page)
        )

    def detachable_intruders_count(self) -> int:
        return _detachable_intruders_count(self._conn)

    def detachable_intruders(self, *, page: int, per_page: int) -> DetachableIntrudersResponse:
        return DetachableIntrudersResponse.model_validate(
            _detachable_intruders(self._conn, page=page, per_page=per_page)
        )

    def persons_sharing_name_form(self, person_id: int) -> list[SharingPersonOut]:
        return [
            SharingPersonOut.model_validate(r)
            for r in _persons_sharing_name_form(self._conn, person_id)
        ]


__all__ = ["PgPersonsQueries"]
