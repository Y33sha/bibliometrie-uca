"""Source OpenAlex : moissonnage, paramètres de requête, champs des works."""

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
    from pipeline.ingestion.openalex.api import OpenalexClient


def _client() -> OpenalexClient:
    from pipeline.ingestion.api_params import API_BASE_URLS
    from pipeline.ingestion.openalex.api import OpenalexClient

    return OpenalexClient(API_BASE_URLS["openalex"])


def _harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.openalex.harvest import OpenalexHarvester

    return OpenalexHarvester(conn, logger, _client())


def _person_harvester(conn: Connection, logger: logging.Logger) -> Harvester:
    from pipeline.ingestion.openalex.person_search import OpenalexPersonHarvester

    return OpenalexPersonHarvester(conn, logger, _client())


def _doi_search() -> DoiSearch:
    from pipeline.ingestion.openalex.fetch_missing import OpenalexDoiSearch

    return OpenalexDoiSearch()


def _stale_refetch() -> StaleRefetch:
    from pipeline.ingestion.openalex.fetch_stale import OpenalexStaleRefetch

    return OpenalexStaleRefetch()


def _normalizer() -> type[SourceNormalizer]:
    from pipeline.ingestion.openalex.normalize import OpenalexNormalizer

    return OpenalexNormalizer


ADAPTER = SourceAdapter(
    source=Source.OPENALEX,
    stale_refetch=_stale_refetch,
    normalizer=_normalizer,
    harvester=_harvester,
    person_harvester=_person_harvester,
    doi_search=_doi_search,
)
