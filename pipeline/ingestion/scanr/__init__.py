"""Source ScanR : moissonnage et champs des documents.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity
from pipeline.ingestion.scanr.fields import extract_dois, extract_id


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    scanr_id = extract_id(record)
    return RecordIdentity.of(scanr_id, *extract_dois(record)) if scanr_id else None


READER = PayloadReader(
    source=Source.SCANR,
    identify=_identify,
)
