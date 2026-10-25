"""Port SerialRepository — édition de l'agrégat Serial dans l'administration.

L'agrégat Publisher est dans `publisher_repository.py` (principe ISP). Les deux agrégats sont liés par `serials.publisher_id` (FK) mais manipulés par des opérations distinctes — séparer les ports réduit la surface sur laquelle chaque call site s'engage.

La méthode `find_shared_title_serial_pairs` vit ici : c'est une query sur la table `serials`, appelée par le service de fusion d'éditeurs pour détecter les conflits avant `merge_publisher_into`.
"""

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
    """Champs éditables d'une revue, en modification sélective.

    Seuls les champs explicitement fournis sont écrits (`model_dump(exclude_unset=True)`). Les champs listés sont ceux qu'un client peut fournir ; `title_normalized`, dérivé de `title`, est posé par le repository.

    `serial_type` et `oa_model` ont les types du domaine, que les enums SQL des mêmes noms reprennent. Leurs valeurs se vérifient ici.
    """

    title: str | None = None
    issns: list[SerialIssnInput] | None = None
    oa_model: OaModel | None = None
    serial_type: SerialType | None = None
    is_academic: bool | None = None
    apc_amount: float | None = None


class SerialRepository(Protocol):
    """Contrat d'édition de l'agrégat Serial dans l'administration."""

    def find_by_id(self, serial_id: int) -> Serial | None:
        """Hydrate l'aggregate `Serial` complet. Retourne None si le journal n'existe pas. Les `serial_name_forms` restent une projection séparée, hors de l'aggregate."""
        ...

    def save(self, serial: Serial) -> None:
        """Persiste une revue chargée : UPDATE de ses champs éditables par l'API. `title_normalized` est re-dérivé du titre ; les colonnes gérées par le pipeline ne sont pas touchées. Lève `NotFoundError` si l'id est absent."""
        ...

    def find_shared_title_serial_pairs(
        self,
        target_publisher_id: int,
        source_publisher_id: int,
    ) -> list[SharedTitlePair]:
        """Paires de revues (une du `target_publisher_id`, une du `source_publisher_id`) partageant le même `title_normalized`, avec leurs titres et leurs ISSN."""
        ...
