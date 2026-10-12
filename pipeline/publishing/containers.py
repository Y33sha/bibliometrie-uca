"""Accès PostgreSQL du pipeline aux conteneurs d'un document : revues et monographies, sur une même connexion."""

from pipeline.publishing.journals.journals import JournalGatewayQueries
from pipeline.publishing.monographs.monographs import MonographGatewayQueries


class ContainerGatewayQueries(JournalGatewayQueries, MonographGatewayQueries):
    """Accès PostgreSQL à `journals` et `monographs`, sur une même connexion."""
