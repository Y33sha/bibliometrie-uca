"""Port StructureRepository — contrat d'accès à l'agrégat Structure.

Implémenté par infrastructure/repositories/structure_repository.py.
"""

from typing import Protocol


class StructureRepository(Protocol):
    """Contrat d'accès aux 3 tables du concept Structure
    (structures, structure_relations, structure_name_forms)."""

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
        api_ids: dict | None,
    ) -> dict: ...

    def update_structure_fields(
        self,
        structure_id: int,
        sql_fragments: list[str],
        params: list,
    ) -> dict: ...

    def delete_structure(self, structure_id: int) -> dict | None: ...

    # ── structure_relations ────────────────────────────────────────

    def create_relation(
        self,
        *,
        parent_id: int,
        child_id: int,
        relation_type: str,
    ) -> dict | None: ...

    def delete_relation(self, relation_id: int) -> dict | None: ...

    # ── structure_name_forms ───────────────────────────────────────

    def name_form_exists(self, form_id: int) -> bool: ...

    def create_name_form(
        self,
        *,
        structure_id: int,
        form_text_normalized: str,
        is_word_boundary: bool,
        is_excluding: bool,
        requires_context_of: list | None,
    ) -> dict: ...

    def update_name_form_fields(
        self,
        form_id: int,
        sql_fragments: list[str],
        params: list,
    ) -> dict: ...

    def delete_name_form(self, form_id: int) -> dict | None: ...
