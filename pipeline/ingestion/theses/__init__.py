"""Source theses.fr : moissonnage et champs des thèses.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity
from pipeline.ingestion.theses.fields import extract_doi, extract_id


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    theses_id = extract_id(record)
    return RecordIdentity.of(theses_id, extract_doi(record)) if theses_id else None


READER = PayloadReader(
    source=Source.THESES,
    identify=_identify,
)
