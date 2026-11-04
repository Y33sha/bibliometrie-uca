"""Source OpenAlex : moissonnage, paramètres de requête, champs des works.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity
from pipeline.ingestion.openalex.fields import extract_doi, extract_openalex_id
from pipeline.ingestion.openalex.payload import authors_may_be_truncated


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    if not record.get("id"):
        return None
    return RecordIdentity.of(extract_openalex_id(record), extract_doi(record))


READER = PayloadReader(
    source=Source.OPENALEX,
    identify=_identify,
    authors_truncated=authors_may_be_truncated,
)
