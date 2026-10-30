"""Corps des réponses d'erreur à charge structurée, partagés par les handlers d'`app.py` et les routes qui les déclarent.

Une erreur au seul `{detail}` se passe de modèle. Ces deux-ci contiennent une liste que le frontend affiche : leur contrat est publié dans l'OpenAPI. Elles reprennent, côté HTTP, la forme des `TypedDict` de `domain/errors.py`.
"""

from application.ports.model import Model


class BlockingSerialItem(Model):
    """Paire de revues qui empêche la fusion de deux éditeurs."""

    target_serial_id: int
    target_title: str
    source_serial_id: int
    source_title: str
    reason: str


class PublisherMergeBlockedResponse(Model):
    """409 de `POST /api/publishers/{id}/merge` : la fusion est refusée en bloc, `blocking_serials` énumère les paires à traiter."""

    detail: str
    blocking_serials: list[BlockingSerialItem]


class RejectedPairItem(Model):
    """Paire (publication, personne) déjà rejetée, qui bloque une réattribution."""

    publication_id: int
    person_id: int
    rejected_at: str


class RejectedPairsResponse(Model):
    """409 des attributions de contributions sources orphelines : `rejected_pairs` énumère les paires rejetées, à confirmer avec `force`."""

    detail: str
    rejected_pairs: list[RejectedPairItem]
