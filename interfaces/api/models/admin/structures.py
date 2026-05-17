"""Modèles Pydantic pour les structures (référentiel institutionnel)."""

from datetime import datetime

from pydantic import BaseModel

# ----- Entrées (POST/PUT/PATCH) -----


class StructureCreate(BaseModel):
    code: str
    name: str
    acronym: str | None = None
    type: str
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    # Pré-coercion : `str` toléré et wrappé en list par `StructureApiIds`
    # côté repo. Output (`StructureOut.api_ids`) est `dict[str, list[str]]`.
    api_ids: dict[str, str | list[str]] | None = None


class StructureUpdate(BaseModel):
    name: str | None = None
    acronym: str | None = None
    type: str | None = None
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict[str, str | list[str]] | None = None


class RelationCreate(BaseModel):
    parent_id: int
    child_id: int
    relation_type: str


class NameFormCreate(BaseModel):
    structure_id: int
    form_text: str
    is_word_boundary: bool = False
    is_excluding: bool = False
    requires_context_of: list[int] | None = None


class NameFormUpdate(BaseModel):
    form_text: str | None = None
    is_word_boundary: bool | None = None
    is_excluding: bool | None = None
    requires_context_of: list[int] | None = None


# ----- Sorties -----


class StructureListItem(BaseModel):
    """Ligne résumée de `/api/structures` (liste + recherche)."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str


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


class StructureRelationOut(BaseModel):
    """Relation structure-à-structure."""

    id: int
    parent_id: int
    child_id: int
    relation_type: str


class StructureRelationCreateResponse(BaseModel):
    """Réponse de POST /api/structure-relations.

    Polymorphe : soit la relation créée, soit `{status: "already_exists"}`.
    """

    id: int | None = None
    parent_id: int | None = None
    child_id: int | None = None
    relation_type: str | None = None
    status: str | None = None
