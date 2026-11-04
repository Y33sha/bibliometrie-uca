"""Source HAL : moissonnage, client de l'API Solr, champs des documents.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity
from pipeline.ingestion.hal.fields import extract_doi, extract_id
from pipeline.ingestion.hal.hash_normalize import strip_volatile_for_hash


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    hal_id = extract_id(record)
    return RecordIdentity.of(hal_id, extract_doi(record)) if hal_id else None


READER = PayloadReader(
    source=Source.HAL,
    identify=_identify,
    strip_volatile=strip_volatile_for_hash,
)
