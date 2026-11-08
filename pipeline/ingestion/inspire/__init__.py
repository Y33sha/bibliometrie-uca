"""Source INSPIRE-HEP : base disciplinaire de la physique des hautes énergies.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity
from pipeline.ingestion.inspire.payload import record_dois, record_id


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    """Renvoie l'identifiant natif d'une fiche INSPIRE, son numéro, et ses DOI."""
    number = record_id(record)
    return RecordIdentity.of(number, *record_dois(record)) if number else None


READER = PayloadReader(source=Source.INSPIRE, identify=_identify)
