"""Source theses.fr : moissonnage et champs des thèses."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import RecordIdentity, SourceAdapter

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from pipeline.ingestion.common.harvester import Harvester
    from pipeline.ingestion.common.normalizer import SourceNormalizer
    from pipeline.ingestion.common.stale_refetch import StaleRefetch
    from pipeline.ingestion.theses.api import ThesesClient


def _client() -> ThesesClient:
    from pipeline.ingestion.api_params import API_BASE_URLS
    from pipeline.ingestion.theses.api import ThesesClient

    return ThesesClient(API_BASE_URLS["theses"])


def _harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.theses.harvest import ThesesHarvester

    return ThesesHarvester(conn, logger, _client())


def _stale_refetch() -> StaleRefetch:
    from pipeline.ingestion.theses.fetch_stale import ThesesStaleRefetch

    return ThesesStaleRefetch()


def _normalizer() -> type[SourceNormalizer]:
    from pipeline.ingestion.theses.normalize import ThesesNormalizer

    return ThesesNormalizer


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    from pipeline.ingestion.theses.fields import extract_doi, extract_id

    theses_id = extract_id(record)
    return RecordIdentity.of(theses_id, extract_doi(record)) if theses_id else None


ADAPTER = SourceAdapter(
    source=Source.THESES,
    identify=_identify,
    stale_refetch=_stale_refetch,
    normalizer=_normalizer,
    harvester=_harvester,
)
