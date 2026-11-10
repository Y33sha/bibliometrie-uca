"""Adaptateur de la source, câblé par les phases."""

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.ops.fetch_missing import fetch_by_source_id
from pipeline.ingestion.ops.harvest import OpsHarvester
from pipeline.ingestion.ops.normalize import OpsNormalizer

ADAPTER = SourceAdapter(
    source=Source.OPS,
    fetch_by_native_id=fetch_by_source_id,
    normalizer=OpsNormalizer,
    harvester=lambda conn, logger: OpsHarvester(conn, logger, None),
)
