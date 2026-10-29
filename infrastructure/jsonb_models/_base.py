"""Base commune des modèles de colonne JSONB."""

from collections.abc import Mapping

from pydantic import BaseModel

from domain.types import JsonValue


class JsonbModel(BaseModel):
    """Base des modèles de colonne JSONB."""

    def to_dict(self) -> Mapping[str, JsonValue]:
        """Sérialise pour l'écriture en base, sans les clés nulles."""
        return self.model_dump(exclude_none=True)
