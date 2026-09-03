"""Fixtures partagées entre les tests unitaires des normalizers.

Les doublures des ports d'écriture sont les mêmes pour toutes les sources : un normalizer verse ses documents dans `source_publications` et marque sa ligne de staging traitée, quel que soit le format qu'il lit.
"""

import logging

import pytest

from application.ports.pipeline.normalize.source_publications import SourcePublicationRow
from application.ports.pipeline.normalize.staging import StagingRow


@pytest.fixture
def logger() -> logging.Logger:
    """Logger neutre pour les normalizers sous test (aucune sortie disque)."""
    return logging.getLogger("test_normalize")


class FakeSourcePublicationQueries:
    """Doublure du port `SourcePublicationQueries` : retient les documents versés."""

    def __init__(self) -> None:
        self.upserted_documents: list[SourcePublicationRow] = []

    def upsert_source_publication(self, conn, row: SourcePublicationRow) -> int:
        self.upserted_documents.append(row)
        return 999


class FakeStagingQueries:
    """Doublure du port `StagingQueries` : retient les lignes marquées traitées."""

    def __init__(self) -> None:
        self.marked_done: list[int] = []

    def mark_done(self, conn, staging_id: int) -> None:
        self.marked_done.append(staging_id)


@pytest.fixture
def source_publication_queries() -> FakeSourcePublicationQueries:
    return FakeSourcePublicationQueries()


@pytest.fixture
def staging_queries() -> FakeStagingQueries:
    return FakeStagingQueries()


@pytest.fixture
def staging_row():
    """Fabrique de lignes de staging, identifiées par leur `staging_id`."""

    def _row(staging_id: int = 1, source_id: str = "10.1/a", doi: str | None = None, raw=None):
        return StagingRow(id=staging_id, source_id=source_id, doi=doi, raw_data=raw or {})

    return _row
