"""Port MonographRepository — édition à la main de l'agrégat Monograph."""

from typing import Protocol

from pydantic import BaseModel

from domain.monographs.monograph import Monograph


class MonographUpdate(BaseModel):
    """Champs éditables d'une monographie, en modification sélective : seuls les champs fournis sont écrits."""

    title: str | None = None
    proceedings: bool | None = None
    year: int | None = None


class MonographRepository(Protocol):
    """Chargement et persistance de l'agrégat Monograph."""

    def find_by_id(self, monograph_id: int) -> Monograph | None:
        """L'agrégat complet, ou `None` si la monographie n'existe pas."""
        ...

    def save(self, monograph: Monograph) -> None:
        """Écrit les champs éditables. `title_normalized` dérive de `title`. Lève `NotFoundError` si l'id est absent."""
        ...
