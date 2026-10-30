"""Attribution à une personne des identifiants de ses contributions sources, en phase `persons`.

L'attribution passe par le repository des personnes (`PgPersonRepository.attribute_identifier`), partagé avec l'API.
"""

import logging
from collections.abc import Mapping, Sequence

from domain.errors import ValidationError
from domain.persons.identifiers import PERSON_IDENTIFIER_TYPES, IdentifierOrigin
from infrastructure.repositories.person_repository import PgPersonRepository

logger = logging.getLogger(__name__)


def add_identifiers_from_contributions(
    person_id: int,
    contributions: Sequence[Mapping[str, str]],
    *,
    repo: PgPersonRepository,
) -> None:
    """Attribue en `pending` à la personne les identifiants observés dans ses contributions sources.

    Une valeur mal formée est journalisée et écartée. Une valeur déjà attribuée à une autre personne en `pending` ou `confirmed` reste à cette personne. L'arbitrage des conflits d'attribution du run suivant tranche le conflit.

    Args:
        contributions: identifiants de chaque contribution source, `{id_type: valeur}`.
    """
    seen: set[tuple[str, str]] = set()
    for a in contributions:
        for id_type in PERSON_IDENTIFIER_TYPES:
            value = a.get(id_type)
            if not value or (id_type, value) in seen:
                continue
            seen.add((id_type, value))
            try:
                repo.attribute_identifier(person_id, id_type, value, source=IdentifierOrigin.AUTO)
            except ValidationError:
                logger.warning("Identifiant mal formé ignoré : %s=%r", id_type, value)
