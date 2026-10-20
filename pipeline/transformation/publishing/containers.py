"""Stores des conteneurs d'un document : revues et monographies, sur une même connexion."""

from typing import NamedTuple, Self

from sqlalchemy import Connection

from pipeline.transformation.publishing.journals.store import JournalStore
from pipeline.transformation.publishing.monographs.store import MonographStore


class ContainerStores(NamedTuple):
    """Revues et monographies, sur une même connexion."""

    journals: JournalStore
    monographs: MonographStore

    @classmethod
    def of(cls, conn: Connection) -> Self:
        return cls(JournalStore(conn), MonographStore(conn))
