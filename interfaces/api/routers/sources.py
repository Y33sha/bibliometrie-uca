"""Router des sources bibliographiques. Sert `/api/sources`."""

from fastapi import APIRouter

from domain.sources.registry import ALL_SOURCES, source_label
from interfaces.api.models import EnumOption

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("", response_model=list[EnumOption])
def list_sources() -> list[EnumOption]:
    """Sources et leur libellé, dans l'ordre d'affichage."""
    return [EnumOption(value=source, label_fr=source_label(source)) for source in ALL_SOURCES]
