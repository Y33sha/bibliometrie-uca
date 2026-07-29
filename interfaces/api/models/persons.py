"""Modèles Pydantic du router des personnes admin : corps des requêtes entrantes et réponses composées après mutation."""

from typing import Literal

from pydantic import BaseModel

from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from interfaces.api.models.authorships import SourceAuthorshipRef

# ----- Corps des requêtes -----


class AddIdentifier(BaseModel):
    # Le service restreint l'ajout manuel aux types publics (`PUBLIC_PERSON_IDENTIFIER_TYPES`).
    id_type: PersonIdentifierType
    id_value: str


class UpdateIdentifierStatus(BaseModel):
    # `authenticated` est exclu : posé seulement par l'import ORCID, protégé par un trigger.
    status: Literal[
        AttributionStatus.PENDING, AttributionStatus.CONFIRMED, AttributionStatus.REJECTED
    ]


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
    status: Literal[
        AttributionStatus.PENDING, AttributionStatus.CONFIRMED, AttributionStatus.REJECTED
    ]


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
    """Identifiant après changement de statut : son id et son statut."""

    id: int
    status: str


class NameFormStatusResponse(BaseModel):
    """Forme de nom après changement de statut, pour la personne concernée."""

    person_id: int
    name_form: str
    status: str


class IdentifierReassignResponse(BaseModel):
    """Identifiant après réattribution : la personne à laquelle il est rattaché et son statut."""

    id: int
    person_id: int
    status: str


class DetachAuthorshipsResponse(BaseModel):
    """Décompte d'un détachement de signatures : signatures détachées, authorships supprimées, formes de nom nettoyées."""

    detached: int
    deleted_authorships: int
    cleaned_forms: int
