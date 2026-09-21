"""Port des conteneurs d'un document, revue et monographie, consommé par les normaliseurs. Servi par `PgContainerGatewayQueries` (`infrastructure/pipeline/containers.py`)."""

from typing import Protocol

from application.ports.pipeline.journals import JournalFindOrCreateQueries
from application.ports.pipeline.monographs import MonographFindOrCreateQueries


class ContainerFindOrCreateQueries(
    JournalFindOrCreateQueries, MonographFindOrCreateQueries, Protocol
):
    """Trouve ou crée la revue et la monographie qui contiennent un document."""
