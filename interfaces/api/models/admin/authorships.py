"""Modèles Pydantic pour les authorships admin (exclusion, orphelines)."""

from pydantic import BaseModel

# ----- Entrées -----


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


class ExcludeSourceAuthorship(BaseModel):
    excluded: bool = True


# ----- Sorties -----


class OrphanCountResponse(BaseModel):
    total: int


class OrphanAuthorshipOut(BaseModel):
    source: str
    authorship_id: int
    full_name: str
    last_name: str
    first_name: str
    publication_id: int
    pub_title: str
    pub_year: int | None


class OrphanAuthorshipsResponse(BaseModel):
    total: int
    page: int
    pages: int
    authorships: list[OrphanAuthorshipOut]


# ----- Réponses mutations -----


class AuthorshipExcludeResponse(BaseModel):
    id: int
    excluded: bool


class ExcludeSourceAuthorshipResponse(BaseModel):
    ok: bool
    excluded: bool


class OrphanAssignResponse(BaseModel):
    ok: bool = True
    person_id: int


class OrphanBatchAssignResponse(BaseModel):
    ok: bool = True
    assigned: int
