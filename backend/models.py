"""Pydantic models shared across routers."""

from typing import Literal
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


class SetCountry(BaseModel):
    countries: list[str] | None = None

class BatchSetCountry(BaseModel):
    country_code: str
    address_ids: list[int] | None = None
    search: str = ""
    has_country: str = ""
    country_code_filter: str = ""
    suggested_country: str = ""


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
    is_excluding: bool = False
    requires_context_of: list[int] | None = None


class NameFormUpdate(BaseModel):
    form_text: str | None = None
    is_word_boundary: bool | None = None
    is_excluding: bool | None = None
    requires_context_of: list[int] | None = None


# ----- Journals / Publishers -----

class JournalUpdate(BaseModel):
    title: str | None = None
    issn: str | None = None
    eissn: str | None = None
    issnl: str | None = None
    doi_prefix: str | None = None
    oa_model: str | None = None
    journal_type: str | None = None
    is_academic: bool | None = None
    is_predatory: bool | None = None
    is_in_doaj: bool | None = None
    apc_amount: float | None = None
    notes: str | None = None

class PublisherUpdate(BaseModel):
    name: str | None = None
    country: str | None = None
    doi_prefix: str | None = None
    is_predatory: bool | None = None
    notes: str | None = None

class MergeRequest(BaseModel):
    source_id: int

# ----- Publications -----

class MergePublications(BaseModel):
    target_id: int
    source_id: int

class MarkDistinctPublications(BaseModel):
    pub_id_a: int
    pub_id_b: int

class ExcludeSourceAuthorship(BaseModel):
    excluded: bool = True


# ----- Persons -----

class LinkPersonAuthor(BaseModel):
    author_id: int
    source: str  # 'hal' or 'openalex'


class AddIdentifier(BaseModel):
    id_type: str   # 'orcid' or 'idhal'
    id_value: str

class UpdateIdentifierStatus(BaseModel):
    status: Literal["pending", "confirmed", "rejected"]

class ReassignIdentifier(BaseModel):
    person_id: int

class RejectPerson(BaseModel):
    rejected: bool = True

class UpdatePersonName(BaseModel):
    last_name: str
    first_name: str = ""

class MergePersons(BaseModel):
    source_id: int

class MarkPersonsDistinct(BaseModel):
    person_id_a: int
    person_id_b: int

class CreatePersonName(BaseModel):
    last_name: str
    first_name: str = ""

class SourceAuthorshipRef(BaseModel):
    source: str
    authorship_id: int

class AssignOrphanAuthorship(BaseModel):
    source: str
    authorship_id: int
    person_id: int | None = None
    create_person: CreatePersonName | None = None

class BatchAssignOrphanAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]
    person_id: int

class DetachAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]
    name_form: str = ""

class DetachNameForm(BaseModel):
    name_form: str
