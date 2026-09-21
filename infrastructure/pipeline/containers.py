"""Adapter PostgreSQL des conteneurs d'un document : revues et monographies, sur une même connexion.

Sert `ContainerFindOrCreateQueries` (normaliseurs) et `MonographSeriesQueries` (séries des monographies) par la réunion des deux adaptateurs.
"""

from infrastructure.pipeline.journals import PgJournalGatewayQueries
from infrastructure.pipeline.monographs import PgMonographGatewayQueries


class PgContainerGatewayQueries(PgJournalGatewayQueries, PgMonographGatewayQueries):
    """Accès PostgreSQL à `journals` et `monographs`, sur une même connexion."""
