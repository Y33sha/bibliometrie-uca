"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.common.lookup import one_at_a_time
from pipeline.ingestion.hal.api import HalClient, find_deposit
from pipeline.ingestion.hal.fetch_missing import search_doi
from pipeline.ingestion.hal.harvest import HalHarvester
from pipeline.ingestion.hal.normalize import HalNormalizer
from pipeline.ingestion.hal.person_search import HalPersonHarvester

ADAPTER = SourceAdapter(
    source=Source.HAL,
    fetch_by_native_id=find_deposit,
    normalizer=HalNormalizer,
    harvester=lambda conn, logger: HalHarvester(conn, logger, HalClient()),
    person_harvester=lambda conn, logger: HalPersonHarvester(conn, logger, HalClient()),
    doi_search=DoiSearch(one_at_a_time(search_doi)),
)
