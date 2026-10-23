"""Source ScanR : moissonnage et champs des documents."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from pipeline.ingestion.common.doi_search import DoiSearch
    from pipeline.ingestion.common.harvester import Harvester
    from pipeline.ingestion.common.normalizer import SourceNormalizer
    from pipeline.ingestion.common.stale_refetch import StaleRefetch
    from pipeline.ingestion.scanr.api import ScanrClient


def _client() -> ScanrClient:
    from pipeline.ingestion.api_params import API_BASE_URLS
    from pipeline.ingestion.credentials import get_scanr_credentials
    from pipeline.ingestion.scanr.api import ScanrClient

    return ScanrClient(API_BASE_URLS["scanr"], credentials=get_scanr_credentials())


def _harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.scanr.harvest import ScanrHarvester

    return ScanrHarvester(conn, logger, _client())


def _person_harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.scanr.person_search import ScanrPersonHarvester

    return ScanrPersonHarvester(conn, logger, _client())


def _doi_search() -> DoiSearch:
    from pipeline.ingestion.scanr.fetch_missing import ScanrDoiSearch

    return ScanrDoiSearch()


def _stale_refetch() -> StaleRefetch:
    from pipeline.ingestion.scanr.fetch_stale import ScanrStaleRefetch

    return ScanrStaleRefetch()


def _normalizer() -> type[SourceNormalizer]:
    from pipeline.ingestion.scanr.normalize import ScanrNormalizer

    return ScanrNormalizer


ADAPTER = SourceAdapter(
    source=Source.SCANR,
    stale_refetch=_stale_refetch,
    normalizer=_normalizer,
    harvester=_harvester,
    person_harvester=_person_harvester,
    doi_search=_doi_search,
)
