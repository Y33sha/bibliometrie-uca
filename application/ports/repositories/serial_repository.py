"""Port SerialRepository : édition de l'entité Serial dans l'administration."""

from typing import Protocol

from application.ports.model import Model
from domain.publishers.merge import SharedTitlePair
from domain.serials.issns import IssnStatus, IssnSupport
from domain.serials.serial import OaModel, Serial, SerialType


class SerialIssnInput(Model):
    """ISSN d'une revue, saisi dans l'administration."""

    issn: str
    support: IssnSupport | None = None
    linking: bool = False
    status: IssnStatus = IssnStatus.ACTIVE


class SerialUpdate(Model):
    """Champs modifiables d'une revue. Seuls les champs fournis sont écrits."""

    title: str | None = None
    issns: list[SerialIssnInput] | None = None
    oa_model: OaModel | None = None
    serial_type: SerialType | None = None
    is_academic: bool | None = None


class SerialRepository(Protocol):
    """Contrat d'édition de l'entité Serial dans l'administration."""

    def find_by_id(self, serial_id: int) -> Serial | None:
        """Charge l'entité `Serial`, ou `None` si la revue n'existe pas. Ses formes de nom sont hors de l'entité."""
        ...

    def save(self, serial: Serial) -> None:
        """Enregistre les champs modifiables d'une revue chargée. Lève `NotFoundError` si la revue n'existe pas."""
        ...

    def find_shared_title_serial_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[SharedTitlePair]:
        """Renvoie les paires de revues de même titre normalisé, l'une de l'éditeur cible, l'autre de l'éditeur absorbé, avec leurs titres et leurs ISSN."""
        ...
