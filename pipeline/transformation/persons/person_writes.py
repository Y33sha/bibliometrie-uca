"""Règles de la phase `persons` sur une personne : changement de nom, identifiants observés dans ses signatures.

Les écritures passent par le repository des personnes (`PgPersonRepository`), que l'API utilise aussi. Les règles communes sont dans `domain.persons` : nom requis (`validated_name`), formes de nom (`compute_person_name_forms`), attribution d'un identifiant (`attribution_outcome`).
"""

import logging
from collections.abc import Mapping, Sequence

from domain.errors import ValidationError
from domain.persons.identifier_attribution import (
    AttributionOutcome,
    IdentifierAttribution,
    attribution_outcome,
)
from domain.persons.identifiers import (
    PERSON_IDENTIFIER_TYPES,
    IdentifierOrigin,
    normalized_identifier_value,
)
from domain.persons.name_forms import compute_person_name_forms
from domain.persons.person import validated_name
from domain.types import JsonValue
from infrastructure.repositories.person_repository import PgPersonRepository

logger = logging.getLogger(__name__)


def rename_person(
    person_id: int, last_name: str, first_name: str, *, repo: PgPersonRepository
) -> None:
    """Change le nom d'une personne et recalcule aussitôt ses formes de nom. Lève `ValidationError` sans patronyme."""
    last_name, first_name = validated_name(last_name, first_name)
    repo.update_name(person_id, last_name, first_name)
    repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))


def add_identifiers_from_authorships(
    person_id: int,
    authorships: Sequence[Mapping[str, JsonValue]],
    *,
    repo: PgPersonRepository,
) -> None:
    """Attribue en `pending` à la personne les identifiants observés dans ses signatures, donnés par `{id_type: valeur}`.

    Une valeur mal formée est journalisée et écartée. Une valeur déjà attribuée à une autre personne en `pending` ou `confirmed` est laissée : l'arbitrage par consensus du run suivant la tranche.
    """
    seen: set[tuple[str, str]] = set()
    for a in authorships:
        for id_type in PERSON_IDENTIFIER_TYPES:
            raw = a.get(id_type)
            if not raw:
                continue
            # `hal_person_id` arrive en int, les autres en str ; la colonne est en text.
            value = str(raw)
            if (id_type, value) in seen:
                continue
            seen.add((id_type, value))
            try:
                _add_identifier(person_id, id_type, value, repo=repo)
            except ValidationError:
                logger.warning("Identifiant mal formé ignoré : %s=%r", id_type, value)


def _add_identifier(
    person_id: int, id_type: str, id_value: str, *, repo: PgPersonRepository
) -> None:
    """Attribue un identifiant à la personne selon `attribution_outcome`. Un identifiant détenu par une autre personne reste à elle."""
    id_value = normalized_identifier_value(id_type, id_value)
    existing = repo.find_identifier(id_type, id_value)
    outcome = attribution_outcome(existing, person_id)
    if outcome is AttributionOutcome.ADDED:
        repo.insert_identifier(
            IdentifierAttribution(
                id=None,
                person_id=person_id,
                id_type=id_type,
                id_value=id_value,
                source=IdentifierOrigin.AUTO,
            )
        )
    elif existing is not None and outcome is AttributionOutcome.REASSIGNED:
        existing.reattribute_to(person_id, source=IdentifierOrigin.AUTO)
        repo.update_identifier(existing)
