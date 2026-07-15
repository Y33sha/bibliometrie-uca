"""Query services pour /api/structures/* et /api/name-forms/*.

`PgStructuresQueries` hérite explicitement du Protocol `application.ports.api.structures_queries.StructuresQueries`.
"""

from typing import Any

from sqlalchemy import Connection, text

from application.ports.api.structures_queries import (
    NameFormOut,
    RelatedStructureOut,
    StructureDetailResponse,
    StructureListItem,
    StructureOut,
    StructuresQueries,
)

_LIST_ORDER_BY = """
    ORDER BY CASE s.structure_type::text
        WHEN 'labo' THEN 1
        WHEN 'universite' THEN 2
        WHEN 'onr' THEN 3
        WHEN 'chu' THEN 4
        WHEN 'ecole' THEN 5
        WHEN 'site' THEN 6
        ELSE 7
    END, s.name
"""


def _list_structures_sql(*, type_filter: str | None, search: str) -> tuple[str, dict[str, Any]]:
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
    sql = f"""
        SELECT s.id, s.code, s.name, s.acronym, s.structure_type::text AS type,
               COALESCE(
                   array_agg(ps.perimeter_id) FILTER (WHERE ps.perimeter_id IS NOT NULL),
                   '{{}}'
               ) AS perimeter_ids
        FROM structures s
        LEFT JOIN perimeter_structures ps ON ps.structure_id = s.id
        WHERE {where}
        GROUP BY s.id, s.code, s.name, s.acronym, s.structure_type
        {_LIST_ORDER_BY}
    """
    return sql, binds


def _related_from_row(row: Any) -> RelatedStructureOut:
    return RelatedStructureOut(
        id=row.id,
        code=row.code,
        name=row.name,
        acronym=row.acronym,
        type=row.type,
        relation_id=row.relation_id,
        relation_type=row.relation_type,
    )


def _name_form_from_row(row: Any) -> NameFormOut:
    return NameFormOut(
        id=row.id,
        structure_id=row.structure_id,
        form_text=row.form_text,
        is_word_boundary=row.is_word_boundary,
        is_excluding=row.is_excluding,
        requires_context_of=list(row.requires_context_of) if row.requires_context_of else None,
        created_at=row.created_at,
    )


class PgStructuresQueries(StructuresQueries):
    """Adapter SA pour `application.ports.api.structures_queries.StructuresQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_structures(self, *, type_filter: str | None, search: str) -> list[StructureListItem]:
        """Liste des structures, filtrable par type et recherche accent-insensible.

        Tri canonique par type (labo > universite > onr > chu > ecole > site > autres) puis nom.
        """
        sql, binds = _list_structures_sql(type_filter=type_filter, search=search)
        rows = self._conn.execute(text(sql), binds).all()
        return [
            StructureListItem(
                id=r.id,
                code=r.code,
                name=r.name,
                acronym=r.acronym,
                type=r.type,
                perimeter_ids=list(r.perimeter_ids),
            )
            for r in rows
        ]

    def get_structure_detail(self, structure_id: int) -> StructureDetailResponse | None:
        """Détail complet : structure + parents + enfants + formes de noms.

        Retourne `None` si la structure n'existe pas (caller = 404).
        """
        struct_row = self._conn.execute(
            text("""
                SELECT id, code, name, acronym, structure_type::text AS type,
                       ror_id, rnsr_id, hal_collection, api_ids
                FROM structures WHERE id = :id
            """),
            {"id": structure_id},
        ).one_or_none()
        if not struct_row:
            return None

        parent_rows = self._conn.execute(
            text("""
                SELECT sr.id AS relation_id, sr.relation_type::text,
                       sp.id, sp.code, sp.name, sp.acronym, sp.structure_type::text AS type
                FROM structure_relations sr
                JOIN structures sp ON sp.id = sr.parent_id
                WHERE sr.child_id = :id
                ORDER BY sr.relation_type, sp.name
            """),
            {"id": structure_id},
        ).all()

        child_rows = self._conn.execute(
            text("""
                SELECT sr.id AS relation_id, sr.relation_type::text,
                       sc.id, sc.code, sc.name, sc.acronym, sc.structure_type::text AS type
                FROM structure_relations sr
                JOIN structures sc ON sc.id = sr.child_id
                WHERE sr.parent_id = :id
                ORDER BY sr.relation_type, sc.name
            """),
            {"id": structure_id},
        ).all()

        form_rows = self._conn.execute(
            text("""
                SELECT * FROM structure_name_forms
                WHERE structure_id = :id
                ORDER BY form_text
            """),
            {"id": structure_id},
        ).all()

        return StructureDetailResponse(
            structure=StructureOut(
                id=struct_row.id,
                code=struct_row.code,
                name=struct_row.name,
                acronym=struct_row.acronym,
                type=struct_row.type,
                ror_id=struct_row.ror_id,
                rnsr_id=struct_row.rnsr_id,
                hal_collection=struct_row.hal_collection,
                api_ids=struct_row.api_ids,
            ),
            parents=[_related_from_row(r) for r in parent_rows],
            children=[_related_from_row(r) for r in child_rows],
            forms=[_name_form_from_row(r) for r in form_rows],
        )

    def get_name_form(self, form_id: int) -> NameFormOut | None:
        """Forme de nom par id. None si absente."""
        row = self._conn.execute(
            text("SELECT * FROM structure_name_forms WHERE id = :id"),
            {"id": form_id},
        ).one_or_none()
        return _name_form_from_row(row) if row else None
