"""Corps des réponses d'erreur à charge structurée, partagés par les handlers d'`app.py` et les routes qui les déclarent.

Les erreurs à corps trivial (`{detail}`) n'ont pas de modèle : leur forme est universelle. Ces deux-ci portent une liste que le frontend affiche, d'où un contrat publié dans l'OpenAPI. Elles reprennent la forme des `TypedDict` de `domain/errors.py`, côté HTTP.
"""

from pydantic import BaseModel


class BlockingJournalItem(BaseModel):
    """Paire de revues qui empêche la fusion de deux éditeurs."""

    target_journal_id: int
    target_title: str
    source_journal_id: int
    source_title: str
    reason: str


class PublisherMergeBlockedResponse(BaseModel):
    """409 de `POST /api/publishers/{id}/merge` : la fusion est refusée en bloc, `blocking_journals` énumère les paires à traiter."""

    detail: str
    blocking_journals: list[BlockingJournalItem]


class RejectedPairItem(BaseModel):
    """Paire (publication, personne) déjà rejetée, qui bloque une réassignation."""

    publication_id: int
    person_id: int
    rejected_at: str


class RejectedPairsResponse(BaseModel):
    """409 des attributions de signatures orphelines : `rejected_pairs` énumère les paires rejetées, à confirmer avec `force`."""

    detail: str
    rejected_pairs: list[RejectedPairItem]
