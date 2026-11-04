"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.common.lookup import one_at_a_time
from pipeline.ingestion.openalex.api import OpenalexClient, fetch_work, search_doi
from pipeline.ingestion.openalex.harvest import OpenalexHarvester
from pipeline.ingestion.openalex.normalize import OpenalexNormalizer
from pipeline.ingestion.openalex.person_search import OpenalexPersonHarvester

ADAPTER = SourceAdapter(
    source=Source.OPENALEX,
    fetch_by_native_id=fetch_work,
    normalizer=OpenalexNormalizer,
    harvester=lambda conn, logger: OpenalexHarvester(conn, logger, OpenalexClient()),
    person_harvester=lambda conn, logger: OpenalexPersonHarvester(conn, logger, OpenalexClient()),
    doi_search=DoiSearch(one_at_a_time(search_doi)),
)
