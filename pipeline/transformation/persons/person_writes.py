"""Attribution à une personne des identifiants de ses contributions sources, en phase `persons`.

L'attribution passe par le repository des personnes (`PgPersonRepository.attribute_identifier`), partagé avec l'API.
"""

from collections.abc import Mapping, Sequence

from domain.persons.identifiers import IdentifierOrigin, PersonIdentifierType
from infrastructure.repositories.person_repository import PgPersonRepository


def add_identifiers_from_contributions(
    person_id: int,
    contributions: Sequence[Mapping[str, str]],
    *,
    repo: PgPersonRepository,
) -> None:
    """Attribue en `pending` à la personne les identifiants observés dans ses contributions sources.

    Une valeur déjà attribuée à une autre personne en `pending` ou `confirmed` reste à cette personne. L'arbitrage des conflits d'attribution du run suivant tranche le conflit.

    Args:
        contributions: identifiants de chaque contribution source, `{id_type: valeur}`, sous leur forme normalisée à l'ingestion (`compact_identifiers`).
    """
    seen: set[tuple[str, str]] = set()
    for a in contributions:
        for id_type in PersonIdentifierType:
            value = a.get(id_type)
            if not value or (id_type, value) in seen:
                continue
            seen.add((id_type, value))
            repo.attribute_identifier(person_id, id_type, value, source=IdentifierOrigin.AUTO)
