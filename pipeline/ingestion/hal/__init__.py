"""Source HAL : moissonnage, client de l'API Solr, champs des enregistrements sources."""

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
    from pipeline.ingestion.hal.api import HalClient


def _client() -> HalClient:
    from pipeline.ingestion.api_params import API_BASE_URLS
    from pipeline.ingestion.hal.api import HalClient

    return HalClient(API_BASE_URLS["hal"])


def _harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.hal.harvest import HalHarvester

    return HalHarvester(conn, logger, _client())


def _person_harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.hal.person_search import HalPersonHarvester

    return HalPersonHarvester(conn, logger, _client())


def _doi_search() -> DoiSearch:
    from pipeline.ingestion.hal.fetch_missing import HalDoiSearch

    return HalDoiSearch()


def _stale_refetch() -> StaleRefetch:
    from pipeline.ingestion.hal.fetch_stale import HalStaleRefetch

    return HalStaleRefetch()


def _normalizer() -> type[SourceNormalizer]:
    from pipeline.ingestion.hal.normalize import HalNormalizer

    return HalNormalizer


def _strip_volatile(raw_data: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    from pipeline.ingestion.hal.hash_normalize import strip_volatile_for_hash

    return strip_volatile_for_hash(raw_data)


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    from pipeline.ingestion.hal.fields import extract_doi, extract_id

    hal_id = extract_id(record)
    return RecordIdentity.of(hal_id, extract_doi(record)) if hal_id else None


ADAPTER = SourceAdapter(
    source=Source.HAL,
    identify=_identify,
    stale_refetch=_stale_refetch,
    normalizer=_normalizer,
    harvester=_harvester,
    person_harvester=_person_harvester,
    doi_search=_doi_search,
    strip_volatile=_strip_volatile,
)
