"""Source Crossref : recherche par DOI et par personne, nouvelle lecture des documents.

Ce module donne la lecture des documents reçus de la source (`READER`). L'adaptateur de la source est dans `adapter.py`.
"""

from collections.abc import Mapping

from domain.documents.identifiers import DOI
from domain.sources.registry import Source
from domain.types import JsonValue, as_str
from pipeline.ingestion.common.adapter import PayloadReader, RecordIdentity


def _identify(record: Mapping[str, JsonValue]) -> RecordIdentity | None:
    """Renvoie l'identifiant natif d'une œuvre Crossref : son DOI."""
    doi = DOI.normalize(as_str(record.get("DOI")))
    return RecordIdentity.of(doi, doi) if doi else None


READER = PayloadReader(
    source=Source.CROSSREF,
    identify=_identify,
)
