"""Port : lectures sur les personnes (consommé par le router persons).

Implémenté par `infrastructure.queries.persons.PgPersonsQueries`.

Les dataclasses `DirectoryFilters` / `ListFilters` / `FacetFilters`
vivent ici (source de vérité) ; les fonctions infra les importent
depuis ce module pour typer leurs signatures (cf. règle 3
d'`architecture.md`).
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DirectoryFilters:
    search: str = ""
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""
    has_rh: str = ""


@dataclass(frozen=True, slots=True)
class ListFilters:
    search: str = ""
    department: str = ""
    role: str = ""
    linked: str = ""
    has_orcid: str = ""
    has_idhal: str = ""
    has_rh: str = ""


@dataclass(frozen=True, slots=True)
class FacetFilters:
    departments: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    has_orcid: str = ""
    has_idhal: str = ""
    has_idref: str = ""
    has_rh: str = ""
    linked: str = ""


class PersonsQueries(Protocol):
    """Lectures sync pour /api/persons/* + endpoints admin associés."""

    # ── Annuaire / recherche / liste admin ─────────────────────────

    def persons_directory(
        self, *, filters: DirectoryFilters, page: int, per_page: int, sort: str
    ) -> dict[str, Any]: ...

    def search_persons(self, *, q: str, limit: int) -> list[dict[str, Any]]: ...

    def list_persons(
        self, *, filters: ListFilters, page: int, per_page: int, sort: str
    ) -> dict[str, Any]: ...

    # ── Facettes / listes de référence / stats ─────────────────────

    def persons_facets(self, *, filters: FacetFilters) -> dict[str, Any]: ...

    def list_departments(self) -> list[dict[str, Any]]: ...

    def list_roles(self) -> list[dict[str, Any]]: ...

    def persons_stats(self) -> dict[str, Any]: ...

    # ── Détail d'une personne ──────────────────────────────────────

    def person_profile(self, person_id: int) -> dict[str, Any] | None: ...

    def person_theses(self, person_id: int) -> dict[str, Any]: ...

    def person_addresses(self, person_id: int, *, page: int, per_page: int) -> dict[str, Any]: ...

    def person_dashboard(self, person_id: int) -> dict[str, Any]: ...

    def person_subjects(self, person_id: int, *, limit: int) -> list[dict[str, Any]]: ...

    # ── Admin : existence, orphan authorships, name forms ──────────

    def person_exists(self, person_id: int) -> bool: ...

    def orphan_authorships_count(self) -> dict[str, Any]: ...

    def list_orphan_authorships(
        self, *, search: str, page: int, per_page: int
    ) -> dict[str, Any]: ...

    def name_form_authorships(self, person_id: int, name_form: str) -> dict[str, Any]: ...

    def name_form_remaining_authorships(self, person_id: int, name_form: str) -> int: ...
