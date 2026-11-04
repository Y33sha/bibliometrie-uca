"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.common.doi_search import DoiSearch
from pipeline.ingestion.datacite.api import DataciteClient, fetch_doi
from pipeline.ingestion.datacite.fetch_missing import BATCH_SIZE, find_dois
from pipeline.ingestion.datacite.harvest import DataciteHarvester
from pipeline.ingestion.datacite.normalize import DataciteNormalizer
from pipeline.ingestion.datacite.person_search import DatacitePersonHarvester

ADAPTER = SourceAdapter(
    source=Source.DATACITE,
    fetch_by_native_id=fetch_doi,
    normalizer=DataciteNormalizer,
    harvester=lambda conn, logger: DataciteHarvester(conn, logger, DataciteClient()),
    person_harvester=lambda conn, logger: DatacitePersonHarvester(conn, logger, DataciteClient()),
    doi_search=DoiSearch(find_dois, BATCH_SIZE),
)
