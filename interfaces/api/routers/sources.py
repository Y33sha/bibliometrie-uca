"""Router des sources bibliographiques. Sert `/api/sources` et `/api/sources/structure-ids`."""

from fastapi import APIRouter

from domain.sources.registry import (
    STRUCTURE_API_SOURCES,
    Source,
    source_label,
    structure_ids_label,
)
from interfaces.api.models import EnumOption

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[EnumOption])
def list_sources() -> list[EnumOption]:
    """Liste les sources et leur libellé, dans l'ordre d'affichage."""
    return [EnumOption(value=source, label_fr=source_label(source)) for source in Source]


@router.get("/structure-ids", response_model=list[EnumOption])
def list_structure_id_sources() -> list[EnumOption]:
    """Liste les sources des identifiants de structure (`structures.api_ids`) et le libellé de ces identifiants, dans l'ordre d'affichage."""
    return [
        EnumOption(value=source, label_fr=structure_ids_label(source))
        for source in STRUCTURE_API_SOURCES
    ]
