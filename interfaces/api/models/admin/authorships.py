"""Modèles Pydantic du router des contributions admin : corps des requêtes entrantes et réponses composées après mutation."""

from pydantic import BaseModel

# ----- Corps des requêtes -----


class CreatePersonName(BaseModel):
    last_name: str
    first_name: str = ""


class SourceAuthorshipRef(BaseModel):
    source: str
    authorship_id: int


class AssignOrphanAuthorship(BaseModel):
    """Attribution unitaire, seule à savoir créer la personne au passage.

    `source_authorships.id` est une clé primaire : l'id désigne la signature à lui seul.
    """

    authorship_id: int
    person_id: int | None = None
    create_person: CreatePersonName | None = None
    force: bool = False


class BatchAssignOrphanAuthorships(BaseModel):
    """Attribution en lot à une personne existante."""

    authorship_ids: list[int]
    person_id: int
    force: bool = False


# ----- Réponses composées par le router -----


class OrphanAssignResponse(BaseModel):
    ok: bool = True
    person_id: int


class OrphanBatchAssignResponse(BaseModel):
    ok: bool = True
    assigned: int
