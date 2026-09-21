"""Adapter PostgreSQL des conteneurs d'un document : revues et monographies, sur une même connexion."""

from application.ports.pipeline.containers import ContainerFindOrCreateQueries
from infrastructure.pipeline.journals import PgJournalGatewayQueries
from infrastructure.pipeline.monographs import PgMonographGatewayQueries


class PgContainerGatewayQueries(
    PgJournalGatewayQueries, PgMonographGatewayQueries, ContainerFindOrCreateQueries
):
    """Accès PostgreSQL à `journals` et `monographs` pour les normaliseurs."""
