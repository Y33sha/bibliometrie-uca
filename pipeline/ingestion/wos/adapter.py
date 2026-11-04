"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.wos.api import WosClient, fetch_by_ut
from pipeline.ingestion.wos.fetch_missing import BATCH_SIZE, search_dois
from pipeline.ingestion.wos.harvest import WosHarvester
from pipeline.ingestion.wos.normalize import WosNormalizer

ADAPTER = SourceAdapter(
    source=Source.WOS,
    fetch_by_native_id=fetch_by_ut,
    normalizer=WosNormalizer,
    harvester=lambda conn, logger: WosHarvester(conn, logger, WosClient()),
    doi_search=DoiSearch(search_dois, BATCH_SIZE),
)
