"""Modèles Pydantic (router-only) pour les mutations sur personnes.

Bodies HTTP (POST/PATCH) et réponses construites par le router après
mutation. Les retours de query service (`NameFormAuthorshipRef`,
`OtherPersonOut`, `NameFormAuthorshipsResponse`) vivent dans
`application/ports/api/persons_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4).
"""

from typing import Literal

from pydantic import BaseModel

from interfaces.api.models.admin.authorships import SourceAuthorshipRef

# ----- Entrées (POST/PUT/PATCH) -----


class AddIdentifier(BaseModel):
    id_type: str  # 'orcid' or 'idhal'
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


class DetachAuthorships(BaseModel):
    authorships: list[SourceAuthorshipRef]
    name_form: str = ""


class DetachNameForm(BaseModel):
    name_form: str


# ----- Réponses mutations (construites par le router) -----


class AddIdentifierResponse(BaseModel):
    """Réponse de `POST /api/persons/{id}/identifiers`.

    Polymorphe selon le chemin :
    - doublon exact : `added=False` + `reason`
    - ajout normal  : `added=True` + `id_type` + `id_value`
    - réattribution : en plus, `reassigned=True`
    """

    added: bool
    reason: str | None = None
    id_type: str | None = None
    id_value: str | None = None
    reassigned: bool | None = None


class IdentifierStatusResponse(BaseModel):
    id: int
    status: str


class IdentifierReassignResponse(BaseModel):
    id: int
    person_id: int
    status: str


class DetachAuthorshipsResponse(BaseModel):
    detached: int
    deleted_authorships: int
    cleaned_form: bool
