"""Source OPS : familles de brevets INPADOC de l'API de l'Office européen des brevets.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue, as_str
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity


def _identify(family: Mapping[str, JsonValue]) -> RecordIdentity | None:
    family_id = as_str(family.get("id"))
    return RecordIdentity.of(family_id) if family_id else None


READER = PayloadReader(
    source=Source.OPS,
    identify=_identify,
)
