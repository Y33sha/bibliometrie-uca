"""Query services async pour /api/structures/* et /api/name-forms/*.

Implémente le port `application.ports.structures_queries.AsyncStructuresQueries`
via `PgAsyncStructuresQueries` (constructor injection de l'AsyncConnection
SA). Conformité au port assurée par duck typing : pas d'import du
Protocol depuis `infrastructure/` (règle DDD `infrastructure ⊥
application`).
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class PgAsyncStructuresQueries:
    """Adapter SA pour `application.ports.structures_queries.AsyncStructuresQueries`."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def list_structures(
        self, *, type_filter: str | None, search: str
    ) -> list[dict[str, Any]]:
        """Liste des structures, filtrable par type et recherche accent-insensible.

        Tri canonique par type (labo > universite > onr > chu > ecole > site
        > autres) puis nom.
        """
        parts: list[str] = []
        binds: dict[str, Any] = {}
        if type_filter:
            parts.append("s.structure_type::text = :type_filter")
            binds["type_filter"] = type_filter
        if search:
            parts.append(
                "(unaccent(s.name) ILIKE unaccent(:search)"
                " OR s.acronym ILIKE :search OR s.code ILIKE :search)"
            )
            binds["search"] = f"%{search}%"
        where = " AND ".join(parts) if parts else "TRUE"

        rows = (
            await self._conn.execute(
                text(f"""
                    SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type
                    FROM structures s
                    WHERE {where}
                    ORDER BY CASE s.structure_type::text
                        WHEN 'labo' THEN 1
                        WHEN 'universite' THEN 2
                        WHEN 'onr' THEN 3
                        WHEN 'chu' THEN 4
                        WHEN 'ecole' THEN 5
                        WHEN 'site' THEN 6
                        ELSE 7
                    END, s.name
                """),
                binds,
            )
        ).all()
        return [dict(r._mapping) for r in rows]

    async def get_structure_detail(self, structure_id: int) -> dict[str, Any] | None:
        """Détail complet : structure + parents + enfants + formes de noms.

        Retourne `None` si la structure n'existe pas (caller = 404).
        """
        struct_row = (
            await self._conn.execute(
                text("""
                    SELECT id, code, name, acronym, structure_type::text AS type,
                           ror_id, rnsr_id, hal_collection, api_ids
                    FROM structures WHERE id = :id
                """),
                {"id": structure_id},
            )
        ).one_or_none()
        if not struct_row:
            return None

        parent_rows = (
            await self._conn.execute(
                text("""
                    SELECT sr.id AS relation_id, sr.relation_type::text,
                           sp.id, sp.code, sp.name, sp.acronym, sp.structure_type::text AS type
                    FROM structure_relations sr
                    JOIN structures sp ON sp.id = sr.parent_id
                    WHERE sr.child_id = :id
                    ORDER BY sr.relation_type, sp.name
                """),
                {"id": structure_id},
            )
        ).all()

        child_rows = (
            await self._conn.execute(
                text("""
                    SELECT sr.id AS relation_id, sr.relation_type::text,
                           sc.id, sc.code, sc.name, sc.acronym, sc.structure_type::text AS type
                    FROM structure_relations sr
                    JOIN structures sc ON sc.id = sr.child_id
                    WHERE sr.parent_id = :id
                    ORDER BY sr.relation_type, sc.name
                """),
                {"id": structure_id},
            )
        ).all()

        form_rows = (
            await self._conn.execute(
                text("""
                    SELECT * FROM structure_name_forms
                    WHERE structure_id = :id
                    ORDER BY form_text
                """),
                {"id": structure_id},
            )
        ).all()

        return {
            "structure": dict(struct_row._mapping),
            "parents": [dict(r._mapping) for r in parent_rows],
            "children": [dict(r._mapping) for r in child_rows],
            "forms": [dict(r._mapping) for r in form_rows],
        }

    async def get_name_form(self, form_id: int) -> dict[str, Any] | None:
        """Forme de nom par id. None si absente."""
        row = (
            await self._conn.execute(
                text("SELECT * FROM structure_name_forms WHERE id = :id"),
                {"id": form_id},
            )
        ).one_or_none()
        return dict(row._mapping) if row else None
