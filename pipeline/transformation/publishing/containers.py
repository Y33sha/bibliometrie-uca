"""Stores des conteneurs d'un document : revues et monographies, sur une même connexion."""

from typing import NamedTuple, Self

from sqlalchemy import Connection

from pipeline.transformation.publishing.monographs.store import MonographStore
from pipeline.transformation.publishing.serials.store import SerialStore


class ContainerStores(NamedTuple):
    """Revues et monographies, sur une même connexion."""

    serials: SerialStore
    monographs: MonographStore

    @classmethod
    def of(cls, conn: Connection) -> Self:
        return cls(SerialStore(conn), MonographStore(conn))
