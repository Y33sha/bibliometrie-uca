"""Port StructureRepository — contrat d'accès à l'agrégat Structure."""

from typing import Any, Protocol


class StructureRepository(Protocol):
    """Contrat d'accès aux 3 tables du concept Structure
    (structures, structure_relations, structure_name_forms).

    Les retours `dict[str, Any]` sont des records DB (colonnes
    hétérogènes par table) ; le paramètre `fields: dict[str, Any]`
    porte des couples (colonne, valeur) pour un UPDATE générique
    (les types varient selon la colonne). Ces `Any` sont des
    frontières DB intrinsèques.
    """

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
        fields: dict[str, Any],
    ) -> dict[str, Any]: ...

    def delete_structure(self, structure_id: int) -> dict[str, Any] | None: ...

    # ── structure_relations ────────────────────────────────────────

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
        fields: dict[str, Any],
    ) -> dict[str, Any]: ...

    def delete_name_form(self, form_id: int) -> dict[str, Any] | None: ...
