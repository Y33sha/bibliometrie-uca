"""Page de résultats d'une API de source, décodée par le client de la source."""

from collections.abc import Mapping
from dataclasses import dataclass

from domain.types import JsonValue


@dataclass(frozen=True, slots=True)
class Page:
    """Une page de résultats."""

    records: list[Mapping[str, JsonValue]]
    next_token: str | None
    """Jeton de la page suivante, `None` en fin de résultats."""
    total: int | None = None
    """Nombre de résultats annoncé par la source, quand elle le donne."""
