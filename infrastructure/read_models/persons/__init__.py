"""Query services de lecture autour des personnes (router persons).

Le package est organisé par thème :
- `list` : `list_persons`, `search_persons`, `person_curation`, `person_name_forms`
- `identifiers` : `person_identifiers`, partagée par la liste et le profil
- `facets` : `persons_facets`
- `detail` : `person_profile`, `person_theses`, `person_addresses`,
  `person_dashboard`, `person_subjects`
- `admin` : contributions par forme de nom, files de triage des formes et des identifiants

`PersonsQueries` délègue à ces fonctions, qui construisent les modèles de réponse de `models.py`.
"""

# Annotations différées : sinon `list[int]` est résolu comme le sous-module
# `.list` (le `from .list import …` ci-dessous l'attache au package, et le
# namespace global du __init__ shadow le builtin `list`).
from __future__ import annotations

from sqlalchemy import Connection

from infrastructure.read_models.persons.admin import (
    ambiguous_name_forms as _ambiguous_name_forms,
    ambiguous_name_forms_count as _ambiguous_name_forms_count,
    identifier_conflicts as _identifier_conflicts,
    identifier_conflicts_count as _identifier_conflicts_count,
    name_duplicates as _name_duplicates,
    name_duplicates_count as _name_duplicates_count,
    name_form_contributions as _name_form_contributions,
    persons_sharing_name_form as _persons_sharing_name_form,
)
from infrastructure.read_models.persons.detail import (
    person_addresses as _person_addresses,
    person_dashboard as _person_dashboard,
    person_profile as _person_profile,
    person_subjects as _person_subjects,
    person_theses as _person_theses,
)
from infrastructure.read_models.persons.facets import (
    persons_facets as _persons_facets,
)
from infrastructure.read_models.persons.list import (
    list_persons as _list_persons,
    person_curation as _person_curation,
    person_name_forms as _person_name_forms,
    search_persons as _search_persons,
)
from infrastructure.read_models.persons.models import (
    AmbiguousNameFormsResponse,
    IdentifierConflictsResponse,
    NameDuplicatesResponse,
    NameFormContributionsResponse,
    NameFormSummaryOut,
    PersonAddressesResponse,
    PersonDashboardResponse,
    PersonFilters,
    PersonListResponse,
    PersonOut,
    PersonProfileResponse,
    PersonSearchResult,
    PersonsFacetsResponse,
    PersonThesesResponse,
    SharingPersonOut,
)
from infrastructure.read_models.subjects.models import SubjectFrequency


class PersonsQueries:
    """Lectures sur les personnes."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Liste / recherche ──────────────────────────────────────────

    def search_persons(self, *, search: str, limit: int) -> list[PersonSearchResult]:
        return _search_persons(self._conn, search=search, limit=limit)

    def list_persons(
        self, *, filters: PersonFilters, page: int, per_page: int, sort: str
    ) -> PersonListResponse:
        return _list_persons(self._conn, filters=filters, page=page, per_page=per_page, sort=sort)

    def person_curation(self, person_id: int) -> PersonOut | None:
        return _person_curation(self._conn, person_id)

    # ── Facettes / listes de référence ─────────────────────────────

    def persons_facets(self, *, filters: PersonFilters) -> PersonsFacetsResponse:
        return _persons_facets(self._conn, filters=filters)

    def person_name_forms(self, person_id: int) -> list[NameFormSummaryOut]:
        return _person_name_forms(self._conn, person_id)

    # ── Détail d'une personne ──────────────────────────────────────

    def person_profile(self, person_id: int) -> PersonProfileResponse | None:
        return _person_profile(self._conn, person_id)

    def person_theses(self, person_id: int) -> PersonThesesResponse:
        return _person_theses(self._conn, person_id)

    def person_addresses(
        self, person_id: int, *, page: int, per_page: int
    ) -> PersonAddressesResponse:
        return _person_addresses(self._conn, person_id, page=page, per_page=per_page)

    def person_dashboard(self, person_id: int) -> PersonDashboardResponse:
        return _person_dashboard(self._conn, person_id)

    def person_subjects(self, person_id: int, *, limit: int) -> list[SubjectFrequency]:
        return _person_subjects(self._conn, person_id, limit=limit)

    # ── Admin : name forms ─────────────────────────────────────────

    def name_form_contributions(
        self, person_id: int, name_form: str
    ) -> NameFormContributionsResponse:
        return _name_form_contributions(self._conn, person_id, name_form)

    def ambiguous_name_forms_count(self) -> int:
        return _ambiguous_name_forms_count(self._conn)

    def ambiguous_name_forms(self, *, page: int, per_page: int) -> AmbiguousNameFormsResponse:
        return _ambiguous_name_forms(self._conn, page=page, per_page=per_page)

    def identifier_conflicts_count(self) -> int:
        return _identifier_conflicts_count(self._conn)

    def identifier_conflicts(self, *, page: int, per_page: int) -> IdentifierConflictsResponse:
        return _identifier_conflicts(self._conn, page=page, per_page=per_page)

    def name_duplicates_count(self) -> int:
        return _name_duplicates_count(self._conn)

    def name_duplicates(self, *, page: int, per_page: int) -> NameDuplicatesResponse:
        return _name_duplicates(self._conn, page=page, per_page=per_page)

    def persons_sharing_name_form(self, person_id: int) -> list[SharingPersonOut]:
        return _persons_sharing_name_form(self._conn, person_id)


__all__ = ["PersonsQueries"]
