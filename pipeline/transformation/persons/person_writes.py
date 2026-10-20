"""Identifiants que la phase `persons` attribue à une personne d'après ses signatures.

L'attribution passe par le repository des personnes (`PgPersonRepository.attribute_identifier`), que l'API utilise aussi.
"""

import logging
from collections.abc import Mapping, Sequence

from domain.errors import ValidationError
from domain.persons.identifiers import PERSON_IDENTIFIER_TYPES, IdentifierOrigin
from domain.types import JsonValue
from infrastructure.repositories.person_repository import PgPersonRepository

logger = logging.getLogger(__name__)


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
                repo.attribute_identifier(person_id, id_type, value, source=IdentifierOrigin.AUTO)
            except ValidationError:
                logger.warning("Identifiant mal formé ignoré : %s=%r", id_type, value)
