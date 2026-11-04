"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.credentials import get_scanr_credentials
from pipeline.ingestion.scanr.api import ScanrClient, fetch_by_id
from pipeline.ingestion.scanr.fetch_missing import BATCH_SIZE, search_dois
from pipeline.ingestion.scanr.harvest import ScanrHarvester
from pipeline.ingestion.scanr.normalize import ScanrNormalizer
from pipeline.ingestion.scanr.person_search import ScanrPersonHarvester


def _client() -> ScanrClient:
    return ScanrClient(API_BASE_URLS["scanr"], credentials=get_scanr_credentials())


ADAPTER = SourceAdapter(
    source=Source.SCANR,
    fetch_by_native_id=fetch_by_id,
    normalizer=ScanrNormalizer,
    harvester=lambda conn, logger: ScanrHarvester(conn, logger, _client()),
    person_harvester=lambda conn, logger: ScanrPersonHarvester(conn, logger, _client()),
    doi_search=DoiSearch(search_dois, BATCH_SIZE),
)
