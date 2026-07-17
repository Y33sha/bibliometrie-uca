"""Modèles Pydantic propres au routeur des revues.

Le contrat d'édition `JournalUpdate` vit dans le port `application/ports/repositories/journal_repository.py` ; les DTOs de retour des query services dans `application/ports/api/journals_queries.py`.
"""

from pydantic import BaseModel

from domain.journals.journal import JournalType


class JournalTypeChange(BaseModel):
    """Valeur de `journal_type` dont la modale admin demande l'impact avant de confirmer l'édition."""

    journal_type: JournalType


class JournalTypeChangeImpact(BaseModel):
    """Compte des publications dont le `doc_type` canonique changerait si le `journal_type` passait à la valeur prévue. Renvoyé par le preview de la modale admin avant confirmation de l'édition."""

    count: int
