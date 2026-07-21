"""Modèles Pydantic du router des personnes admin : corps des requêtes entrantes et réponses composées après mutation."""

from typing import Literal

from pydantic import BaseModel

from interfaces.api.models.authorships import SourceAuthorshipRef

# ----- Corps des requêtes -----


class AddIdentifier(BaseModel):
    id_type: str  # 'orcid' ou 'idhal'
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


class MarkDistinctPersons(BaseModel):
    person_id_a: int
    person_id_b: int


class DetachAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]


class UpdateNameFormStatus(BaseModel):
    name_form: str
    status: Literal["pending", "confirmed", "rejected"]


# ----- Réponses composées par le router -----


class AddIdentifierResponse(BaseModel):
    """Réponse de `POST /api/persons/{id}/identifiers`, polymorphe selon l'issue :

    - doublon exact : `added=False` + `reason`
    - ajout : `added=True` + `id_type` + `id_value`
    - réattribution depuis une autre personne : en plus, `reassigned=True`
    """

    added: bool
    reason: str | None = None
    id_type: str | None = None
    id_value: str | None = None
    reassigned: bool | None = None


class IdentifierStatusResponse(BaseModel):
    id: int
    status: str


class NameFormStatusResponse(BaseModel):
    person_id: int
    name_form: str
    status: str


class IdentifierReassignResponse(BaseModel):
    id: int
    person_id: int
    status: str


class DetachAuthorshipsResponse(BaseModel):
    detached: int
    deleted_authorships: int
    cleaned_forms: int
