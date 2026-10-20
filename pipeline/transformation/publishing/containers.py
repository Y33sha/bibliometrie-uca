"""Accès PostgreSQL du pipeline aux conteneurs d'un document : revues et monographies, sur une même connexion."""

from pipeline.transformation.publishing.journals.journals import JournalGatewayQueries
from pipeline.transformation.publishing.monographs.store import MonographStore


class ContainerGatewayQueries(JournalGatewayQueries, MonographStore):
    """Accès PostgreSQL à `journals` et `monographs`, sur une même connexion."""
