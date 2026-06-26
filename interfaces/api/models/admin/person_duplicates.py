"""Modèles Pydantic pour la déduplication de personnes (admin).

Les DTOs de retour du query service (`PersonDedupDetail`, `PersonDuplicatePair`, `PersonConflictPair`, et les sous-types) vivent dans `application/ports/api/person_duplicates_queries.py` (cf. chantier `CODE_typage-projections-strict` Phase 4). Restent ici les wrappers construits par le router.
"""

from pydantic import BaseModel

from application.ports.api.person_duplicates_queries import (
    PersonConflictPair,
    PersonDuplicatePair,
    PersonIdentifierConflictPair,
)


class PersonDuplicatePairResponse(BaseModel):
    pair: PersonDuplicatePair | None


class PersonConflictPairResponse(BaseModel):
    pair: PersonConflictPair | None


class PersonIdentifierConflictPairResponse(BaseModel):
    pair: PersonIdentifierConflictPair | None
