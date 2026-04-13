"""Pydantic models shared across routers."""

from pydantic import BaseModel


# ----- Auth -----

class LoginRequest(BaseModel):
    username: str
    password: str


# ----- Addresses -----

class ReviewAction(BaseModel):
    structure_id: int
    is_confirmed: bool | None  # True = confirmé, False = rejeté, None = reset


class BatchReviewAction(BaseModel):
    address_ids: list[int]
    structure_id: int
    is_confirmed: bool | None


class AssignStructureAction(BaseModel):
    structure_id: int


# ----- Structures -----

class StructureCreate(BaseModel):
    code: str
    name: str
    acronym: str | None = None
    type: str
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict | None = None


class StructureUpdate(BaseModel):
    name: str | None = None
    acronym: str | None = None
    type: str | None = None
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict | None = None


class RelationCreate(BaseModel):
    parent_id: int
    child_id: int
    relation_type: str


class NameFormCreate(BaseModel):
    structure_id: int
    form_text: str
    is_word_boundary: bool = False
    requires_context_of: list | None = None
    notes: str | None = None


class NameFormUpdate(BaseModel):
    form_text: str | None = None
    is_word_boundary: bool | None = None
    requires_context_of: list | None = None
    is_active: bool | None = None
    notes: str | None = None


# ----- Persons -----

class LinkPersonAuthor(BaseModel):
    author_id: int
    source: str  # 'hal' or 'openalex'


class AddIdentifier(BaseModel):
    id_type: str   # 'orcid' or 'idhal'
    id_value: str
