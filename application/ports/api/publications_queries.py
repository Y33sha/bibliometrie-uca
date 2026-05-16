"""Port : lectures sur les publications (consommé par le router publications).

Implémenté par `infrastructure.queries.publications.PgPublicationsQueries`.

Les dataclasses `FacetFilters` et `ListFilters` vivent ici (source de
vérité) ; les fonctions infra les importent depuis ce module pour typer
leurs signatures (cf. règle 3 d'`architecture.md`).
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ListFilters:
    """Bundle des filtres pour list_publications / export_publications.
    Tous les champs ont un défaut — facilite les appels partiels."""

    search: str = ""
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    years: list[int] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    access: str = ""
    oa_status: str = ""
    source_values: list[str] = field(default_factory=list)
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    person_id: int | None = None
    is_corresponding: str = ""
    has_apc: str = ""
    country_values: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: str = ""
    subject_id: int | None = None


@dataclass(frozen=True, slots=True)
class FacetFilters:
    """Bundle spécifique aux facettes (similaire à ListFilters mais sans
    pagination/sort)."""

    years: list[int] = field(default_factory=list)
    lab_ids: list[int] = field(default_factory=list)
    lab_none: bool = False
    doc_types: list[str] = field(default_factory=list)
    excluded_types: list[str] = field(default_factory=list)
    access: str = ""
    oa_status: str = ""
    source_values: list[str] = field(default_factory=list)
    publisher_id: int | None = None
    journal_id: int | None = None
    person_id: int | None = None
    is_corresponding: str = ""
    has_apc: str = ""
    country_values: list[str] = field(default_factory=list)
    hal_status_values: list[str] = field(default_factory=list)
    in_perimeter: str = ""
    subject_id: int | None = None


class PublicationsQueries(Protocol):
    """Lectures sync pour /api/publications/*."""

    def list_publications(
        self,
        *,
        filters: ListFilters,
        apc_structure_ids: list[int],
        page: int,
        per_page: int,
        sort: str,
    ) -> dict[str, Any]: ...

    def publications_facets(
        self, *, filters: FacetFilters, apc_structure_ids: list[int]
    ) -> dict[str, Any]: ...

    def export_publications_csv(
        self, *, filters: ListFilters, apc_structure_ids: list[int], sort: str
    ) -> str: ...

    def export_theses_csv(
        self, *, filters: ListFilters, apc_structure_ids: list[int], sort: str
    ) -> str: ...

    def all_years(self) -> list[int]: ...

    def get_publication_detail(self, pub_id: int) -> dict[str, Any] | None: ...
