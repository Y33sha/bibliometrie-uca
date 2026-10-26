"""Port SerialRepository — édition de l'agrégat Serial dans l'administration."""

from typing import Protocol

from pydantic import BaseModel

from domain.publishers.merge import SharedTitlePair
from domain.serials.issns import IssnStatus, IssnSupport
from domain.serials.serial import OaModel, Serial, SerialType


class SerialIssnInput(BaseModel):
    """Un ISSN d'une revue, saisi à l'administration."""

    issn: str
    support: IssnSupport | None = None
    linking: bool = False
    status: IssnStatus = IssnStatus.ACTIVE
    replaced_by: str | None = None


class SerialUpdate(BaseModel):
    """Champs éditables d'une revue, en modification sélective : seuls les champs explicitement fournis sont écrits."""

    title: str | None = None
    issns: list[SerialIssnInput] | None = None
    oa_model: OaModel | None = None
    serial_type: SerialType | None = None
    is_academic: bool | None = None


class SerialRepository(Protocol):
    """Contrat d'édition de l'agrégat Serial dans l'administration."""

    def find_by_id(self, serial_id: int) -> Serial | None:
        """Charge l'agrégat `Serial`, ou `None` si la revue n'existe pas. Ses formes de nom sont hors de l'agrégat."""
        ...

    def save(self, serial: Serial) -> None:
        """Enregistre les champs éditables d'une revue chargée. Lève `NotFoundError` si la revue n'existe pas."""
        ...

    def find_shared_title_serial_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[SharedTitlePair]:
        """Paires de revues de même titre normalisé, l'une de `target_publisher_id`, l'autre de `source_publisher_id`, avec leurs titres et leurs ISSN."""
        ...
