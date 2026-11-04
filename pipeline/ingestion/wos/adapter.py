"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.credentials import get_wos_api_key
from pipeline.ingestion.wos.api import WosClient, fetch_by_ut
from pipeline.ingestion.wos.fetch_missing import BATCH_SIZE, search_dois
from pipeline.ingestion.wos.harvest import WosHarvester
from pipeline.ingestion.wos.normalize import WosNormalizer


def _client() -> WosClient:
    return WosClient(API_BASE_URLS["wos"], api_key=get_wos_api_key())


ADAPTER = SourceAdapter(
    source=Source.WOS,
    fetch_by_native_id=fetch_by_ut,
    normalizer=WosNormalizer,
    harvester=lambda conn, logger: WosHarvester(conn, logger, _client()),
    doi_search=DoiSearch(search_dois, BATCH_SIZE),
)
