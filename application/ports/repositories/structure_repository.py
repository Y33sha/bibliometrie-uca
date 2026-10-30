"""Port StructureRepository : accès à l'entité Structure."""

from datetime import datetime
from typing import Protocol, TypedDict

from application.ports.model import Model
from domain.structures.structure import Structure, StructureType
from domain.types import JsonValue


class StructureCreate(Model):
    """Champs d'une structure à créer."""

    code: str
    name: str
    acronym: str | None = None
    type: StructureType
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict[str, str | list[str]] | None = None
    """Une valeur seule (`str`) devient une liste à l'écriture (`StructureApiIds`)."""


class NameFormCreate(Model):
    """Champs d'une forme de nom de structure à créer."""

    structure_id: int
    form_text: str
    is_word_boundary: bool = False
    is_excluding: bool = False
    requires_context_of: list[int] | None = None


class StructureUpdate(Model):
    """Champs modifiables d'une structure. Seuls les champs fournis sont écrits. `null` efface un champ facultatif."""

    name: str | None = None
    acronym: str | None = None
    type: StructureType | None = None
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict[str, str | list[str]] | None = None


class NameFormUpdate(Model):
    """Champs modifiables d'une forme de nom de structure. Seuls les champs fournis sont écrits."""

    form_text: str | None = None
    is_word_boundary: bool | None = None
    is_excluding: bool | None = None
    requires_context_of: list[int] | None = None
    """`null` efface la valeur."""


class StructureNameFormUpdateFields(TypedDict, total=False):
    """Champs d'une forme de nom à écrire, `form_text` déjà normalisé."""

    form_text: str
    is_word_boundary: bool
    is_excluding: bool
    requires_context_of: list[int] | None


class StructureTutelleRow(TypedDict):
    """Tutelle renvoyée par la création."""

    id: int
    parent_id: int
    child_id: int


class StructureTutelleDeletedRow(TypedDict):
    """Tutelle supprimée : ses identifiants, pour l'audit."""

    parent_id: int
    child_id: int


class StructureNameFormRow(TypedDict):
    """Forme de nom de structure, renvoyée par la création et la mise à jour."""

    id: int
    structure_id: int
    form_text: str
    created_at: datetime | None
    is_word_boundary: bool
    requires_context_of: list[int] | None
    is_excluding: bool


class StructureNameFormDeletedRow(TypedDict):
    """Forme de nom supprimée : sa structure et son texte, pour l'audit."""

    structure_id: int
    form_text: str


class StructureRepository(Protocol):
    """Accès aux structures, à leurs tutelles et à leurs formes de nom."""

    # ── Entité : chargement et écriture ───────────────────────────

    def find_by_id(self, structure_id: int) -> Structure | None:
        """Charge l'entité `Structure` avec ses formes de nom, ou `None` si la structure n'existe pas. Les tutelles sont hors de l'entité (`get_ancestor_ids`)."""
        ...

    def add(self, structure: Structure) -> int:
        """Insère une structure et renvoie son id. `api_ids` est validé, et posé sous sa forme normalisée sur l'entité."""
        ...

    def save(self, structure: Structure) -> None:
        """Enregistre les champs éditables d'une structure chargée. Le code est immuable. Lève `NotFoundError` si la structure n'existe pas."""
        ...

    def delete_structure(self, structure_id: int) -> dict[str, JsonValue] | None:
        """Supprime la structure et renvoie son instantané, ou `None` si la structure est introuvable.

        L'instantané, pris avant la suppression, contient la ligne `structures`, les formes de nom et les tutelles (`parent_ids`, `child_ids`). Il contient aussi les liens adresse-structure confirmés, rejetés ou manuels (listes d'`address_id`), et les périmètres ayant la structure pour racine.
        """
        ...

    # ── structure_parents ─────────────────────────────────────────

    def get_ancestor_ids(self, structure_id: int) -> frozenset[int]:
        """Renvoie les ancêtres de la structure dans le graphe des tutelles, sans la structure elle-même."""
        ...

    def create_tutelle(
        self,
        *,
        parent_id: int,
        child_id: int,
    ) -> StructureTutelleRow | None:
        """Crée une tutelle et renvoie la ligne, ou `None` si elle existe déjà (`(parent_id, child_id)` en conflit)."""
        ...

    def delete_tutelle(self, tutelle_id: int) -> StructureTutelleDeletedRow | None: ...

    # ── structure_name_forms ───────────────────────────────────────

    def find_name_form(self, form_id: int) -> StructureNameFormRow | None:
        """Charge une forme de nom de structure, pour édition. La lecture pour l'API est `StructuresQueries.get_name_form`."""
        ...

    def create_name_form(
        self,
        *,
        structure_id: int,
        form_text_normalized: str,
        is_word_boundary: bool,
        is_excluding: bool,
        requires_context_of: list[int] | None,
    ) -> StructureNameFormRow: ...

    def update_name_form_fields(
        self,
        form_id: int,
        fields: StructureNameFormUpdateFields,
    ) -> StructureNameFormRow:
        """Écrit les champs donnés (`StructureNameFormUpdateFields`) et renvoie la ligne. Lève `NotFoundError` si la forme est introuvable."""
        ...

    def delete_name_form(self, form_id: int) -> StructureNameFormDeletedRow | None: ...
