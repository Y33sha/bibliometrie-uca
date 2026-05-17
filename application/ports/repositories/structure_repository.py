"""Port StructureRepository — contrat d'accès à l'agrégat Structure."""

from typing import Any, Protocol, TypedDict

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


class StructureRepository(Protocol):
    """Contrat d'accès aux 3 tables du concept Structure
    (structures, structure_relations, structure_name_forms).

    Les retours `dict[str, Any]` sont des records DB (colonnes hétérogènes par table) ; ces `Any` sont des frontières DB intrinsèques, traités par les phases ultérieures du chantier `CODE_typage-projections-strict`.
    """

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
    ) -> dict[str, Any]: ...

    def update_structure_fields(
        self,
        structure_id: int,
        fields: StructureUpdateFields,
    ) -> dict[str, Any]: ...

    def delete_structure(self, structure_id: int) -> dict[str, Any] | None: ...

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
    ) -> dict[str, Any] | None: ...

    def delete_relation(self, relation_id: int) -> dict[str, Any] | None: ...

    # ── structure_name_forms ───────────────────────────────────────

    def name_form_exists(self, form_id: int) -> bool: ...

    def create_name_form(
        self,
        *,
        structure_id: int,
        form_text_normalized: str,
        is_word_boundary: bool,
        is_excluding: bool,
        requires_context_of: list[int] | None,
    ) -> dict[str, Any]: ...

    def update_name_form_fields(
        self,
        form_id: int,
        fields: StructureNameFormUpdateFields,
    ) -> dict[str, Any]: ...

    def delete_name_form(self, form_id: int) -> dict[str, Any] | None: ...
