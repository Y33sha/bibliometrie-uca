"""Modèles Pydantic du router des structures : corps des requêtes entrantes et réponses composées après mutation."""

from pydantic import BaseModel

# ----- Corps des requêtes -----


class StructureCreate(BaseModel):
    code: str
    name: str
    acronym: str | None = None
    type: str
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    # Pré-coercion : `str` toléré et wrappé en list par `StructureApiIds` côté repo. Output (`StructureOut.api_ids`) est `dict[str, list[str]]`.
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


# ----- Réponses composées par le router -----


class StructureRelationCreateResponse(BaseModel):
    """Réponse de POST /api/structures/relations, polymorphe : soit la relation créée, soit `{status: "already_exists"}`."""

    id: int | None = None
    parent_id: int | None = None
    child_id: int | None = None
    relation_type: str | None = None
    status: str | None = None
