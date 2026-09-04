"""Base commune des modèles de colonne JSONB."""

from pydantic import BaseModel

from domain.types import JsonValue


class JsonbModel(BaseModel):
    """Base des modèles de colonne JSONB.

    `to_dict` sérialise pour l'écriture en base en omettant les clés None.
    """

    def to_dict(self) -> dict[str, JsonValue]:
        """Sérialise pour écriture en base (colonne JSONB). Omet les clés None."""
        return self.model_dump(exclude_none=True)
