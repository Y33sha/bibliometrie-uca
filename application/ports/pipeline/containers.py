"""Port des conteneurs d'un document, revue et monographie, consommé par les normaliseurs. Servi par `PgContainerGatewayQueries` (`infrastructure/pipeline/containers.py`)."""

from typing import Protocol

from application.ports.pipeline.journals import JournalFindOrCreateQueries
from application.ports.pipeline.monographs import (
    MonographCollectionQueries,
    MonographFindOrCreateQueries,
)
from domain.journals.journal import JournalType


class ContainerFindOrCreateQueries(
    JournalFindOrCreateQueries, MonographFindOrCreateQueries, Protocol
):
    """Trouve ou crée la revue et la monographie qui contiennent un document."""


class MonographSeriesQueries(MonographCollectionQueries, JournalFindOrCreateQueries, Protocol):
    """Séries des monographies : trouve ou crée la série sans ISSN de plusieurs volumes, et rattache chaque monographie."""

    def set_journal_type_if_unknown(self, journal_id: int, journal_type: JournalType) -> None:
        """Pose le `journal_type` d'une revue encore de type inconnu."""
        ...
