"""Adapter PostgreSQL des conteneurs d'un document : revues et monographies, sur une même connexion.

Sert `ContainerFindOrCreateQueries` (normaliseurs) et `MonographSeriesQueries` (séries des monographies) par la réunion des deux adaptateurs.
"""

from pipeline.containers.journals import JournalGatewayQueries
from pipeline.containers.monographs import MonographGatewayQueries


class ContainerGatewayQueries(JournalGatewayQueries, MonographGatewayQueries):
    """Accès PostgreSQL à `journals` et `monographs`, sur une même connexion."""
