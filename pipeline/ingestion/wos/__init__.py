"""Source Web of Science : moissonnage, requête et champs des records, empreinte des payloads.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity
from pipeline.ingestion.wos.fields import extract_doi, extract_ut
from pipeline.ingestion.wos.hash_normalize import strip_volatile_for_hash


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    ut = extract_ut(record)
    return RecordIdentity.of(ut, extract_doi(record)) if ut else None


READER = PayloadReader(
    source=Source.WOS,
    identify=_identify,
    strip_volatile=strip_volatile_for_hash,
)
