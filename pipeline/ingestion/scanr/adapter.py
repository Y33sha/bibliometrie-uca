"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.scanr.api import ScanrClient, fetch_by_id
from pipeline.ingestion.scanr.fetch_missing import BATCH_SIZE, search_dois
from pipeline.ingestion.scanr.harvest import ScanrHarvester
from pipeline.ingestion.scanr.normalize import ScanrNormalizer
from pipeline.ingestion.scanr.person_search import ScanrPersonHarvester

ADAPTER = SourceAdapter(
    source=Source.SCANR,
    fetch_by_native_id=fetch_by_id,
    normalizer=ScanrNormalizer,
    harvester=lambda conn, logger: ScanrHarvester(conn, logger, ScanrClient()),
    person_harvester=lambda conn, logger: ScanrPersonHarvester(conn, logger, ScanrClient()),
    doi_search=DoiSearch(search_dois, BATCH_SIZE),
)
