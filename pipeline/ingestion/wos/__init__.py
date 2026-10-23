"""Source Web of Science : moissonnage, requête et champs des records, empreinte des payloads."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import RecordIdentity, SourceAdapter

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from pipeline.ingestion.common.doi_search import DoiSearch
    from pipeline.ingestion.common.harvester import Harvester
    from pipeline.ingestion.common.normalizer import SourceNormalizer
    from pipeline.ingestion.common.stale_refetch import StaleRefetch
    from pipeline.ingestion.wos.api import WosClient


def _client() -> WosClient:
    from pipeline.ingestion.api_params import API_BASE_URLS
    from pipeline.ingestion.credentials import get_wos_api_key
    from pipeline.ingestion.wos.api import WosClient

    return WosClient(API_BASE_URLS["wos"], api_key=get_wos_api_key())


def _harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.wos.harvest import WosHarvester

    return WosHarvester(conn, logger, _client())


def _doi_search() -> DoiSearch:
    from pipeline.ingestion.wos.fetch_missing import WosDoiSearch

    return WosDoiSearch()


def _stale_refetch() -> StaleRefetch:
    from pipeline.ingestion.wos.fetch_stale import WosStaleRefetch

    return WosStaleRefetch()


def _normalizer() -> type[SourceNormalizer]:
    from pipeline.ingestion.wos.normalize import WosNormalizer

    return WosNormalizer


def _strip_volatile(raw_data: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    from pipeline.ingestion.wos.hash_normalize import strip_volatile_for_hash

    return strip_volatile_for_hash(raw_data)


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    from pipeline.ingestion.wos.fields import extract_doi, extract_ut

    ut = extract_ut(record)
    return RecordIdentity.of(ut, extract_doi(record)) if ut else None


ADAPTER = SourceAdapter(
    source=Source.WOS,
    identify=_identify,
    stale_refetch=_stale_refetch,
    normalizer=_normalizer,
    harvester=_harvester,
    doi_search=_doi_search,
    strip_volatile=_strip_volatile,
)
