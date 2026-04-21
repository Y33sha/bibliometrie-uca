"""Port AsyncStructureRepository — contrat d'accès à l'agrégat Structure.

Implémenté par infrastructure/repositories/async_structure_repository.py.
"""

from typing import Protocol


class AsyncStructureRepository(Protocol):
    """Contrat async d'accès aux 3 tables du concept Structure
    (structures, structure_relations, structure_name_forms)."""

    # ── structures ─────────────────────────────────────────────────

    async def structure_exists(self, structure_id: int) -> bool: ...

    async def create_structure(
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

    async def update_structure_fields(
        self,
        structure_id: int,
        sql_fragments: list[str],
        params: list,
    ) -> dict: ...

    async def delete_structure(self, structure_id: int) -> dict | None: ...

    # ── structure_relations ────────────────────────────────────────

    async def create_relation(
        self,
        *,
        parent_id: int,
        child_id: int,
        relation_type: str,
    ) -> dict | None: ...

    async def delete_relation(self, relation_id: int) -> dict | None: ...

    # ── structure_name_forms ───────────────────────────────────────

    async def name_form_exists(self, form_id: int) -> bool: ...

    async def create_name_form(
        self,
        *,
        structure_id: int,
        form_text_normalized: str,
        is_word_boundary: bool,
        is_excluding: bool,
        requires_context_of: list | None,
    ) -> dict: ...

    async def update_name_form_fields(
        self,
        form_id: int,
        sql_fragments: list[str],
        params: list,
    ) -> dict: ...

    async def delete_name_form(self, form_id: int) -> dict | None: ...
