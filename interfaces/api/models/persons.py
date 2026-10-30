"""Modèles Pydantic du router des personnes admin : corps des requêtes entrantes et réponses composées après mutation."""

from typing import Literal

from application.ports.model import Model
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType
from domain.persons.person import PersonExclusion
from interfaces.api.models.contributions import SourceContributionRef

# ----- Corps des requêtes -----


class AddIdentifier(Model):
    # Le service restreint l'ajout manuel aux types publics (`PUBLIC_PERSON_IDENTIFIER_TYPES`).
    id_type: PersonIdentifierType
    id_value: str


class UpdateIdentifierStatus(Model):
    # `authenticated` est exclu : posé seulement par l'import ORCID, protégé par un trigger.
    status: Literal[
        AttributionStatus.PENDING, AttributionStatus.CONFIRMED, AttributionStatus.REJECTED
    ]


class SetPersonExclusion(Model):
    exclusion: PersonExclusion | None


class UpdatePersonName(Model):
    last_name: str
    first_name: str = ""


class MarkDistinctPersons(Model):
    person_id_a: int
    person_id_b: int


class DetachContributions(Model):
    contributions: list[SourceContributionRef]


class UpdateNameFormStatus(Model):
    name_form: str
    status: Literal[
        AttributionStatus.PENDING, AttributionStatus.CONFIRMED, AttributionStatus.REJECTED
    ]


# ----- Réponses composées par le router -----


class AddIdentifierResponse(Model):
    """Réponse de `POST /api/persons/{id}/identifiers`, selon l'issue : doublon exact (`added` faux, avec `reason`), ajout (`added` vrai, avec `id_type` et `id_value`), ou réattribution depuis une autre personne (`reassigned` vrai en plus)."""

    added: bool
    reason: str | None = None
    id_type: str | None = None
    id_value: str | None = None
    reassigned: bool | None = None


class IdentifierStatusResponse(Model):
    """Identifiant après changement de statut."""

    id: int
    status: str
    propagated: int
    """Nombre d'identifiants des comptes HAL de l'identifiant passés au même statut."""


class NameFormStatusResponse(Model):
    """Forme de nom après changement de statut, pour la personne concernée."""

    person_id: int
    name_form: str
    status: str


class DetachContributionsResponse(Model):
    """Décompte d'un détachement de contributions."""

    detached: int
    cleaned_forms: int
    """Nombre de formes de nom supprimées."""
