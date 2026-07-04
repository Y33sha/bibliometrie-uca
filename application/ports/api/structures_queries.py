"""Port : lectures sur les structures (consommé par le router structures).

Implémenté par `infrastructure.queries.api.structures.PgStructuresQueries`.

Co-localise les DTOs Pydantic retournés par ce port. Cf. chantier `CODE_typage-projections-strict` Phase 4. `StructureOut` et `NameFormOut` sont aussi utilisés par le router pour valider les retours dict des services applicatifs (`create_structure`, `update_structure`, `create_name_form`…) — l'import depuis le port est légitime côté router.
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class StructureListItem(BaseModel):
    """Ligne résumée de `/api/structures` (liste + recherche)."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    perimeter_ids: list[int]
    """Périmètres auxquels la structure appartient (clôture transitive). Vide = hors périmètre."""


class StructureOut(BaseModel):
    """Structure complète — renvoyée par GET/POST/PUT sur `/api/structures`."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None
    api_ids: dict[str, list[str]] | None


class RelatedStructureOut(BaseModel):
    """Structure voisine (parent/enfant) dans le détail d'une structure."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    relation_id: int
    relation_type: str


class NameFormOut(BaseModel):
    """Forme de nom d'une structure."""

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    is_excluding: bool
    requires_context_of: list[int] | None
    created_at: datetime | None = None


class StructureDetailResponse(BaseModel):
    """Détail complet renvoyé par GET /api/structures/{id}."""

    structure: StructureOut
    parents: list[RelatedStructureOut]
    children: list[RelatedStructureOut]
    forms: list[NameFormOut]


class StructuresQueries(Protocol):
    """Lectures sur les structures, relations et formes de noms."""

    def list_structures(
        self, *, type_filter: str | None, search: str
    ) -> list[StructureListItem]: ...

    def get_structure_detail(self, structure_id: int) -> StructureDetailResponse | None: ...

    def get_name_form(self, form_id: int) -> NameFormOut | None: ...
