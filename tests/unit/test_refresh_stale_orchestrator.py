"""Régressions sur l'orchestrateur `refresh_stale`.

Les trois issues d'un refetch par id natif sont routées correctement :
- record trouvé (hash changé / inchangé) → `save_refreshed` (updated / unchanged) ;
- absence confirmée (`NOT_FOUND`) → `mark_disappeared` ;
- échec transitoire (`None`) → no-op, compté en `errors`, ni sauvé ni marqué disparu.
"""

import asyncio
import logging
from unittest.mock import MagicMock

from application.pipeline.extract.refresh_stale import refresh
from application.ports.pipeline.extract.refresh_stale import (
    NOT_FOUND,
    FetchedRecord,
    StaleRow,
)


class _FakeAdapter:
    source_key = "openalex"
    max_concurrent = 2

    def __init__(self, outcomes: dict) -> None:
        self._outcomes = outcomes
        self.saved: list[str] = []
        self.disappeared: list[str] = []

    def configure(self, conn) -> None:
        pass

    def find_stale(self, conn) -> list[StaleRow]:
        return [StaleRow(staging_id=i, source_id=sid) for i, sid in enumerate(self._outcomes)]

    async def fetch_by_native_id(self, client, source_id):
        return self._outcomes[source_id]

    def save_refreshed(self, conn, source_id: str, record: FetchedRecord) -> bool:
        self.saved.append(source_id)
        return bool(record.raw_data["changed"])

    def mark_disappeared(self, conn, source_id: str) -> None:
        self.disappeared.append(source_id)


def _run(adapter) -> object:
    return asyncio.run(refresh(MagicMock(), adapter, logging.getLogger("test")))


def test_routes_each_outcome():
    adapter = _FakeAdapter(
        {
            "A": FetchedRecord(doi="10.1/a", raw_data={"changed": True}),
            "B": FetchedRecord(doi="10.1/b", raw_data={"changed": False}),
            "C": NOT_FOUND,
            "D": None,
        }
    )
    metrics = _run(adapter)

    assert set(adapter.saved) == {"A", "B"}
    assert adapter.disappeared == ["C"]
    assert metrics.updated == 1
    assert metrics.unchanged == 1
    assert metrics.extras.get("disappeared") == 1
    assert metrics.errors == 1
    assert metrics.total == 4


def test_transient_failure_is_noop():
    # Un échec transitoire ne marque jamais la row disparue (l'absence n'est pas prouvée).
    adapter = _FakeAdapter({"X": None})
    metrics = _run(adapter)
    assert adapter.saved == []
    assert adapter.disappeared == []
    assert metrics.errors == 1


def test_empty_is_noop():
    adapter = _FakeAdapter({})
    metrics = _run(adapter)
    assert metrics.total == 0
    assert adapter.saved == []
