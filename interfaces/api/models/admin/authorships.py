"""Modèles Pydantic (router-only) pour les authorships admin.

Bodies HTTP (POST) et réponses construites par le router après mutation.
Les retours de query service (`OrphanCountResponse`, `OrphanAuthorshipOut`,
`OrphanAuthorshipsResponse`) vivent dans `application/ports/api/persons_queries.py`
(cf. chantier `CODE_typage-projections-strict` Phase 4).
"""

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
    force: bool = False


class BatchAssignOrphanAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]
    person_id: int
    force: bool = False


# ----- Réponses mutations (construites par le router) -----


class AuthorshipExcludeResponse(BaseModel):
    ok: bool


class OrphanAssignResponse(BaseModel):
    ok: bool = True
    person_id: int


class OrphanBatchAssignResponse(BaseModel):
    ok: bool = True
    assigned: int
