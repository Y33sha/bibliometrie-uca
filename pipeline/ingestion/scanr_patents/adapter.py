"""Adaptateur de la source, câblé par les phases."""

from functools import partial

from domain.sources.registry import Source
from pipeline.ingestion.common.adapter import SourceAdapter
from pipeline.ingestion.scanr.api import ScanrClient, ScanrIndex, fetch_by_id
from pipeline.ingestion.scanr_patents.harvest import EXCLUDED_FIELDS, ScanrPatentsHarvester
from pipeline.ingestion.scanr_patents.normalize import ScanrPatentsNormalizer

_INDEX = ScanrIndex.PATENTS

ADAPTER = SourceAdapter(
    source=Source.SCANR_PATENTS,
    fetch_by_native_id=partial(fetch_by_id, index=_INDEX, excludes=EXCLUDED_FIELDS),
    normalizer=ScanrPatentsNormalizer,
    harvester=lambda conn, logger: ScanrPatentsHarvester(conn, logger, ScanrClient(_INDEX)),
)
