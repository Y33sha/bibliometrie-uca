"""Port StructureRepository — contrat d'accès à l'agrégat Structure."""

from datetime import datetime
from typing import Protocol, TypedDict

from domain.structures.structure import Structure


class StructureUpdateFields(TypedDict, total=False):
    """Partial update sur la table `structures`.

    Le service mappe le champ API `type` vers la colonne DB `structure_type` avant d'appeler le repo.
    """

    name: str
    acronym: str | None
    structure_type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None
    api_ids: dict[str, str | list[str]] | None


class StructureNameFormUpdateFields(TypedDict, total=False):
    """Partial update sur la table `structure_name_forms`.

    `form_text` reçu en clair est normalisé par le service via `normalize_text` avant d'être passé au repo.
    """

    form_text: str
    is_word_boundary: bool
    is_excluding: bool
    requires_context_of: list[int] | None


class StructureRow(TypedDict):
    """Ligne `structures` renvoyée par create / update (colonne `structure_type`
    exposée sous l'alias `type`). Alimente le DTO `StructureOut`."""

    id: int
    code: str
    name: str
    acronym: str | None
    type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None
    api_ids: dict[str, list[str]] | None


class StructureDeletedRow(TypedDict):
    """Sous-ensemble renvoyé par delete (identification pour l'audit)."""

    code: str
    name: str


class StructureRelationRow(TypedDict):
    """Ligne `structure_relations` renvoyée par create."""

    id: int
    parent_id: int
    child_id: int
    relation_type: str


class StructureRelationDeletedRow(TypedDict):
    """Sous-ensemble renvoyé par delete (les ids pour l'audit)."""

    parent_id: int
    child_id: int
    relation_type: str


class StructureNameFormRow(TypedDict):
    """Ligne `structure_name_forms` renvoyée par create / update.
    Alimente le DTO `NameFormOut`."""

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
    """Contrat d'accès aux 3 tables du concept Structure
    (structures, structure_relations, structure_name_forms)."""

    # ── Chargement de l'aggregate ──────────────────────────────────

    def find_by_id(self, structure_id: int) -> Structure | None:
        """Hydrate l'aggregate `Structure` complet (champs scalaires +
        VOs `name_forms`). Retourne None si la structure n'existe pas.
        Les `structure_relations` ne sont pas chargées (graphe externe
        à l'aggregate ; voir `get_ancestor_ids` pour les remontées
        ciblées)."""
        ...

    # ── structures ─────────────────────────────────────────────────

    def structure_exists(self, structure_id: int) -> bool: ...

    def create_structure(
        self,
        *,
        code: str,
        name: str,
        acronym: str | None,
        type: str,
        ror_id: str | None,
        rnsr_id: str | None,
        hal_collection: str | None,
        # Pré-coercion : `str` toléré, normalisé en `list[str]` par le repo
        # via `StructureApiIds`. Le post-coercion (DB / aggregate) est
        # `dict[str, list[str]]`.
        api_ids: dict[str, str | list[str]] | None,
    ) -> StructureRow: ...

    def update_structure_fields(
        self,
        structure_id: int,
        fields: StructureUpdateFields,
    ) -> StructureRow: ...

    def delete_structure(self, structure_id: int) -> StructureDeletedRow | None: ...

    # ── structure_relations ────────────────────────────────────────

    def get_ancestor_ids(self, structure_id: int) -> frozenset[int]:
        """Ancêtres stricts de `structure_id` dans le graphe
        `structure_relations` (toutes `relation_type` confondues).
        N'inclut pas `structure_id` lui-même. Sert au service pour
        valider l'absence de cycle avant insertion d'une relation."""
        ...

    def create_relation(
        self,
        *,
        parent_id: int,
        child_id: int,
        relation_type: str,
    ) -> StructureRelationRow | None: ...

    def delete_relation(self, relation_id: int) -> StructureRelationDeletedRow | None: ...

    # ── structure_name_forms ───────────────────────────────────────

    def get_name_form(self, form_id: int) -> StructureNameFormRow | None: ...

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
    ) -> StructureNameFormRow: ...

    def delete_name_form(self, form_id: int) -> StructureNameFormDeletedRow | None: ...
