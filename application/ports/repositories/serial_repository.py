"""Port SerialRepository : édition de l'entité Serial dans l'administration."""

from typing import Protocol

from application.ports.model import Model
from domain.publishers.merge import SharedTitlePair
from domain.serials.serial import OaModel, Serial, SerialType


class SerialUpdate(Model):
    """Champs modifiables d'une revue. Seuls les champs fournis sont écrits."""

    title: str | None = None
    oa_model: OaModel | None = None
    serial_type: SerialType | None = None
    is_academic: bool | None = None


class SerialRepository(Protocol):
    """Contrat d'édition de l'entité Serial dans l'administration."""

    def find_by_id(self, serial_id: int) -> Serial | None:
        """Charge l'entité `Serial`, ou `None` si la revue n'existe pas."""
        ...

    def issnl_of(self, serial_id: int) -> str | None:
        """Renvoie l'ISSN-L de la revue, ou `None` pour une revue sans ISSN."""
        ...

    def record_title_decision(self, source_id: int, target_id: int) -> None:
        """Garde la fusion de la revue sans ISSN `source_id` dans `target_id` : une série de son titre normalisé est rattachée à `target_id`."""
        ...

    def save(self, serial: Serial) -> None:
        """Enregistre les champs modifiables d'une revue chargée. Lève `NotFoundError` si la revue n'existe pas."""
        ...

    def find_shared_title_serial_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[SharedTitlePair]:
        """Renvoie les paires de revues de même titre normalisé, l'une de l'éditeur cible, l'autre de l'éditeur absorbé, avec leurs titres et leurs ISSN-L."""
        ...
