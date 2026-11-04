"""Source DataCite : moissonnage, paramètres de requête, empreinte des ressources JSON:API.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity
from pipeline.ingestion.datacite.fields import record_doi
from pipeline.ingestion.datacite.hash_normalize import strip_volatile_for_hash


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    """Renvoie l'identifiant natif d'une ressource DataCite : son DOI."""
    doi = record_doi(record)
    return RecordIdentity.of(doi, doi) if doi else None


READER = PayloadReader(
    source=Source.DATACITE,
    identify=_identify,
    strip_volatile=strip_volatile_for_hash,
)
