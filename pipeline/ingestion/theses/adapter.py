"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.theses.api import ThesesClient, fetch_thesis
from pipeline.ingestion.theses.harvest import ThesesHarvester
from pipeline.ingestion.theses.normalize import ThesesNormalizer

ADAPTER = SourceAdapter(
    source=Source.THESES,
    fetch_by_native_id=fetch_thesis,
    normalizer=ThesesNormalizer,
    harvester=lambda conn, logger: ThesesHarvester(conn, logger, ThesesClient()),
)
