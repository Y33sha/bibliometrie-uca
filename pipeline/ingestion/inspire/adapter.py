"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.inspire.api import InspireClient, fetch_record
from pipeline.ingestion.inspire.harvest import InspireHarvester
from pipeline.ingestion.inspire.normalize import InspireNormalizer

ADAPTER = SourceAdapter(
    source=Source.INSPIRE,
    fetch_by_native_id=fetch_record,
    normalizer=InspireNormalizer,
    harvester=lambda conn, logger: InspireHarvester(conn, logger, InspireClient()),
)
