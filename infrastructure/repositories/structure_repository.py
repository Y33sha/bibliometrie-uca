"""Adapter PostgreSQL pour les 3 tables du concept Structure :
`structures`, `structure_relations`, `structure_name_forms`.
"""

from typing import Any

from psycopg.types.json import Jsonb as Json


class PgStructureRepository:
    """Accès PostgreSQL à l'agrégat Structure."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    # ── structures ─────────────────────────────────────────────────

    def structure_exists(self, structure_id: int) -> bool:
        """Vrai si la structure existe."""
        self._cur.execute(
            "SELECT id FROM structures WHERE id = %s",
            (structure_id,),
        )
        return self._cur.fetchone() is not None

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
    ) -> dict:
        """Insère une structure et retourne la ligne complète."""
        self._cur.execute(
            """
            INSERT INTO structures (code, name, acronym, structure_type, ror_id,
                                    rnsr_id, hal_collection, api_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, code, name, acronym, structure_type::text AS type,
                      ror_id, rnsr_id, hal_collection, api_ids
            """,
            (
                code,
                name,
                acronym,
                type,
                ror_id,
                rnsr_id,
                hal_collection,
                Json(api_ids) if api_ids else None,
            ),
        )
        return self._cur.fetchone()

    def update_structure_fields(
        self,
        structure_id: int,
        sql_fragments: list[str],
        params: list,
    ) -> dict:
        """UPDATE dynamique + RETURNING de la ligne complète.

        Le service construit la liste `sql_fragments` ("col = %s") et
        les `params` correspondants. Pour les JSONB (api_ids), le
        service pré-wrappe la valeur en Json() côté infra via le
        validator — le repo reçoit un paramètre déjà prêt.
        """
        sets = ", ".join(sql_fragments)
        self._cur.execute(
            f"""
            UPDATE structures SET {sets} WHERE id = %s
            RETURNING id, code, name, acronym, structure_type::text AS type,
                      ror_id, rnsr_id, hal_collection, api_ids
            """,
            params + [structure_id],
        )
        return self._cur.fetchone()

    def delete_structure(self, structure_id: int) -> dict | None:
        """Supprime une structure. Retourne {code, name} de la ligne
        supprimée pour que le service puisse émettre l'audit, ou None
        si elle n'existait pas."""
        self._cur.execute(
            "DELETE FROM structures WHERE id = %s RETURNING code, name",
            (structure_id,),
        )
        return self._cur.fetchone()

    # ── structure_relations ────────────────────────────────────────

    def create_relation(
        self,
        *,
        parent_id: int,
        child_id: int,
        relation_type: str,
    ) -> dict | None:
        """Insère une relation (idempotent). Retourne la ligne ou None si
        elle existait déjà."""
        self._cur.execute(
            """
            INSERT INTO structure_relations (parent_id, child_id, relation_type)
            VALUES (%s, %s, %s)
            ON CONFLICT (parent_id, child_id, relation_type) DO NOTHING
            RETURNING *
            """,
            (parent_id, child_id, relation_type),
        )
        return self._cur.fetchone()

    def delete_relation(self, relation_id: int) -> dict | None:
        """Supprime une relation. Retourne {parent_id, child_id,
        relation_type} pour l'audit, ou None si inexistante."""
        self._cur.execute(
            """
            DELETE FROM structure_relations WHERE id = %s
            RETURNING parent_id, child_id, relation_type::text AS relation_type
            """,
            (relation_id,),
        )
        return self._cur.fetchone()

    # ── structure_name_forms ───────────────────────────────────────

    def name_form_exists(self, form_id: int) -> bool:
        """Vrai si la forme existe."""
        self._cur.execute(
            "SELECT id FROM structure_name_forms WHERE id = %s",
            (form_id,),
        )
        return self._cur.fetchone() is not None

    def create_name_form(
        self,
        *,
        structure_id: int,
        form_text_normalized: str,
        is_word_boundary: bool,
        is_excluding: bool,
        requires_context_of: list | None,
    ) -> dict:
        """Insère une forme de nom. Le service a déjà normalisé le form_text."""
        self._cur.execute(
            """
            INSERT INTO structure_name_forms (structure_id, form_text,
                                    is_word_boundary, is_excluding,
                                    requires_context_of)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                structure_id,
                form_text_normalized,
                is_word_boundary,
                is_excluding,
                requires_context_of or None,
            ),
        )
        return self._cur.fetchone()

    def update_name_form_fields(
        self,
        form_id: int,
        sql_fragments: list[str],
        params: list,
    ) -> dict:
        """UPDATE dynamique + RETURNING de la ligne complète."""
        sets = ", ".join(sql_fragments)
        self._cur.execute(
            f"""
            UPDATE structure_name_forms SET {sets}
            WHERE id = %s RETURNING *
            """,
            params + [form_id],
        )
        return self._cur.fetchone()

    def delete_name_form(self, form_id: int) -> dict | None:
        """Supprime une forme. Retourne {structure_id, form_text} pour
        l'audit, ou None si inexistante."""
        self._cur.execute(
            """
            DELETE FROM structure_name_forms WHERE id = %s
            RETURNING structure_id, form_text
            """,
            (form_id,),
        )
        return self._cur.fetchone()
