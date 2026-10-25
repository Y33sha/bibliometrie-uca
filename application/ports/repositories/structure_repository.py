"""Port StructureRepository — contrat d'accès à l'agrégat Structure."""

from datetime import datetime
from typing import Protocol, TypedDict

from pydantic import BaseModel

from domain.structures.structure import Structure, StructureType
from domain.types import JsonValue


class StructureUpdate(BaseModel):
    """Champs éditables d'une structure, en modification sélective : seuls les champs explicitement fournis sont écrits, et `null` efface un champ facultatif."""

    name: str | None = None
    acronym: str | None = None
    type: StructureType | None = None
    ror_id: str | None = None
    rnsr_id: str | None = None
    hal_collection: str | None = None
    api_ids: dict[str, str | list[str]] | None = None


class NameFormUpdate(BaseModel):
    """Champs éditables d'une forme de nom de structure, en modification sélective : seuls les champs explicitement fournis sont écrits, et `null` efface `requires_context_of`."""

    form_text: str | None = None
    is_word_boundary: bool | None = None
    is_excluding: bool | None = None
    requires_context_of: list[int] | None = None


class StructureNameFormUpdateFields(TypedDict, total=False):
    """Partial update sur la table `structure_name_forms`.

    `form_text` reçu en clair est normalisé par le service via `normalize_text` avant d'être passé au repo.
    """

    form_text: str
    is_word_boundary: bool
    is_excluding: bool
    requires_context_of: list[int] | None


class StructureRow(TypedDict):
    """Ligne `structures` renvoyée par create / update (colonne `structure_type` exposée sous l'alias `type`). Alimente le DTO `StructureOut`."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None
    api_ids: dict[str, list[str]] | None


class StructureTutelleRow(TypedDict):
    """Ligne `structure_parents` renvoyée par create."""

    id: int
    parent_id: int
    child_id: int


class StructureTutelleDeletedRow(TypedDict):
    """Sous-ensemble renvoyé par delete (les ids pour l'audit)."""

    parent_id: int
    child_id: int


class StructureNameFormRow(TypedDict):
    """Ligne `structure_name_forms` renvoyée par create / update. Alimente le DTO `NameFormOut`."""

    id: int
    structure_id: int
    form_text: str
    created_at: datetime | None
    is_word_boundary: bool
    requires_context_of: list[int] | None
    is_excluding: bool


class StructureNameFormDeletedRow(TypedDict):
    """Sous-ensemble renvoyé par delete (structure + texte pour l'audit)."""

    structure_id: int
    form_text: str


class StructureRepository(Protocol):
    """Contrat d'accès aux 3 tables du concept Structure (structures, structure_parents, structure_name_forms)."""

    # ── structures : charger-muter-sauver l'agrégat ────────────────

    def find_by_id(self, structure_id: int) -> Structure | None:
        """Hydrate l'aggregate `Structure` complet (champs scalaires + VOs `name_forms`). Retourne None si la structure n'existe pas. Les `structure_parents` restent un graphe externe à l'aggregate (voir `get_ancestor_ids` pour les remontées ciblées)."""
        ...

    def add(self, structure: Structure) -> int:
        """Insère une structure neuve et retourne son id. Canonise `api_ids` (validation du schéma JSONB) et pose la forme canonique sur l'entité."""
        ...

    def save(self, structure: Structure) -> None:
        """Persiste une structure chargée : UPDATE de ses champs éditables (`code` immuable exclu). Lève `NotFoundError` si l'id est absent."""
        ...

    def delete_structure(self, structure_id: int) -> dict[str, JsonValue] | None:
        """Supprime la structure et retourne son instantané, pris avant la suppression : la ligne `structures`, ses formes de nom, ses tutelles (`parent_ids`, `child_ids`), ses liens adresse-structure confirmés, rejetés ou manuels (listes d'`address_id`) et les périmètres dont elle est une racine. `None` si elle n'existe pas."""
        ...

    # ── structure_parents ─────────────────────────────────────────

    def get_ancestor_ids(self, structure_id: int) -> frozenset[int]:
        """Ancêtres stricts de `structure_id` dans le graphe `structure_parents`. Exclut `structure_id` lui-même. Sert au service pour valider l'absence de cycle avant insertion d'une tutelle."""
        ...

    def create_tutelle(
        self,
        *,
        parent_id: int,
        child_id: int,
    ) -> StructureTutelleRow | None:
        """Crée une tutelle parent-enfant et retourne la ligne, ou `None` si elle existe déjà (`(parent_id, child_id)` en conflit)."""
        ...

    def delete_tutelle(self, tutelle_id: int) -> StructureTutelleDeletedRow | None: ...

    # ── structure_name_forms ───────────────────────────────────────

    def find_name_form(self, form_id: int) -> StructureNameFormRow | None:
        """Charge la ligne d'agrégat d'une forme de nom de structure, pour édition. La lecture-projection pour l'API vit dans les read-models (`StructuresQueries.get_name_form`)."""
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
        """Applique une modification sélective (`StructureNameFormUpdateFields`) et retourne la ligne. Lève `NotFoundError` si la forme est introuvable."""
        ...

    def delete_name_form(self, form_id: int) -> StructureNameFormDeletedRow | None: ...
