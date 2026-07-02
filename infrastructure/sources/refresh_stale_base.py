"""Classe de base des adapters `refresh_stale` : opérations DB génériques.

Seul `fetch_by_native_id` (l'appel HTTP par identifiant natif) et la
configuration (URL, auth) sont source-spécifiques. La sélection des rows stale,
la persistance du refresh et le marquage de disparition sont identiques d'une
source à l'autre : ils vivent ici, factorisés depuis `infrastructure.sources.common`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.refresh_stale import (
    FetchedRecord,
    FetchOutcome,
    StaleRow,
)
from infrastructure.sources.common import (
    get_stale_rows,
    set_disappeared_by_source_id,
    upsert_staging,
)


class BaseRefreshStaleAdapter(ABC):
    """Base commune : `find_stale`, `save_refreshed`, `mark_disappeared`.

    Les sous-classes fixent `source_key`, `max_concurrent`, `configure` et
    implémentent `fetch_by_native_id`.
    """

    source_key: str
    max_concurrent: int

    @abstractmethod
    def configure(self, conn: Connection) -> None: ...

    @abstractmethod
    async def fetch_by_native_id(
        self, client: httpx.AsyncClient, source_id: str
    ) -> FetchOutcome: ...

    def find_stale(self, conn: Connection) -> list[StaleRow]:
        return [
            StaleRow(staging_id=sid, source_id=src_id)
            for sid, src_id in get_stale_rows(conn, self.source_key)
        ]

    def save_refreshed(self, conn: Connection, source_id: str, record: FetchedRecord) -> bool:
        _, changed = upsert_staging(
            conn,
            source=self.source_key,
            source_id=source_id,
            doi=record.doi,
            raw_data=record.raw_data,
        )
        return changed

    def mark_disappeared(self, conn: Connection, source_id: str) -> None:
        set_disappeared_by_source_id(conn, self.source_key, source_id)
