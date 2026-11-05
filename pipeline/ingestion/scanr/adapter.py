"""Adaptateur de la source, câblé par les phases."""

from functools import partial

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.scanr.api import ScanrClient, ScanrIndex, fetch_by_id
from pipeline.ingestion.scanr.fetch_missing import BATCH_SIZE, search_dois
from pipeline.ingestion.scanr.harvest import ScanrHarvester
from pipeline.ingestion.scanr.normalize import ScanrNormalizer
from pipeline.ingestion.scanr.person_search import ScanrPersonHarvester

_INDEX = ScanrIndex.PUBLICATIONS

ADAPTER = SourceAdapter(
    source=Source.SCANR,
    fetch_by_native_id=partial(fetch_by_id, index=_INDEX),
    normalizer=ScanrNormalizer,
    harvester=lambda conn, logger: ScanrHarvester(conn, logger, ScanrClient(_INDEX)),
    person_harvester=lambda conn, logger: ScanrPersonHarvester(conn, logger, ScanrClient(_INDEX)),
    doi_search=DoiSearch(search_dois, BATCH_SIZE),
)
