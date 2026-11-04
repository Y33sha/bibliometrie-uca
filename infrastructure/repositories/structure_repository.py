"""Repository PostgreSQL des structures, de leurs tutelles et de leurs formes de nom."""

from typing import cast

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Connection, Text, bindparam, cast as sql_cast, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.structure_repository import (
    StructureColumns,
    StructureNameFormDeletedRow,
    StructureNameFormRow,
    StructureNameFormUpdateFields,
    StructureRepository,
    StructureRow,
    StructureTutelleDeletedRow,
    StructureTutelleRow,
)
from domain.errors import NotFoundError, ValidationError
from domain.types import JsonValue
from infrastructure.db.tables import (
    structure_name_forms,
    structure_parents,
    structures,
)
from infrastructure.jsonb_models.structure import StructureApiIds

_NAME_FORM_COLUMNS = (
    structure_name_forms.c.id,
    structure_name_forms.c.structure_id,
    structure_name_forms.c.form_text,
    structure_name_forms.c.created_at,
    structure_name_forms.c.is_word_boundary,
    structure_name_forms.c.requires_context_of,
    structure_name_forms.c.is_excluding,
)
"""Colonnes de `structure_name_forms` renvoyées par create / update / get (RETURNING ou SELECT)."""


_STRUCTURE_COLUMNS = (
    structures.c.id,
    structures.c.code,
    structures.c.name,
    structures.c.acronym,
    sql_cast(structures.c.structure_type, Text).label("type"),
    structures.c.ror_id,
    structures.c.rnsr_id,
    structures.c.hal_collection,
    structures.c.api_ids,
)
"""Colonnes de `structures` renvoyées par l'insertion et la mise à jour (`StructureRow`)."""


def _normalize_api_ids(raw: dict[str, str | list[str]] | None) -> dict[str, list[str]] | None:
    """Renvoie la forme normalisée de `api_ids` (`StructureApiIds`), ou `None` pour une entrée vide. Lève `ValidationError` si le schéma est violé.

    La validation se fait dans le repository : toute écriture passe par lui, y compris celle des scripts hors couche application.
    """
    if not raw:
        return None
    try:
        return StructureApiIds(**raw).to_dict() or None
    except PydanticValidationError as e:
        raise ValidationError(f"api_ids invalide : {e}") from e


def _values(columns: StructureColumns) -> dict[str, object]:
    """Renvoie les valeurs SQL des colonnes fournies, `api_ids` validé et normalisé."""
    values: dict[str, object] = dict(columns)
    if "api_ids" in columns:
        values["api_ids"] = _normalize_api_ids(columns["api_ids"])
    return values


class PgStructureRepository(StructureRepository):
    """Accès PostgreSQL sync aux structures, à leurs tutelles et à leurs formes de nom."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── structures ─────────────────────────────────────────────────

    def add(self, code: str, columns: StructureColumns) -> StructureRow:
        row = self._conn.execute(
            structures.insert().values(code=code, **_values(columns)).returning(*_STRUCTURE_COLUMNS)
        ).one()
        return cast(StructureRow, dict(row._mapping))

    def update(self, structure_id: int, columns: StructureColumns) -> StructureRow | None:
        row = self._conn.execute(
            update(structures)
            .where(structures.c.id == structure_id)
            .values(**_values(columns))
            .returning(*_STRUCTURE_COLUMNS)
        ).first()
        return cast(StructureRow, dict(row._mapping)) if row else None

    def delete_structure(self, structure_id: int) -> dict[str, JsonValue] | None:
        snapshot = self._conn.execute(
            text("""
                SELECT jsonb_build_object(
                    'structure', to_jsonb(s),
                    'name_forms', COALESCE(
                        (SELECT jsonb_agg(to_jsonb(f) - 'structure_id' ORDER BY f.id)
                         FROM structure_name_forms f WHERE f.structure_id = s.id),
                        '[]'::jsonb),
                    'parent_ids', ARRAY(
                        SELECT parent_id FROM structure_parents WHERE child_id = s.id),
                    'child_ids', ARRAY(
                        SELECT child_id FROM structure_parents WHERE parent_id = s.id),
                    'confirmed_address_ids', ARRAY(
                        SELECT address_id FROM address_structures
                        WHERE structure_id = s.id AND is_confirmed),
                    'rejected_address_ids', ARRAY(
                        SELECT address_id FROM address_structures
                        WHERE structure_id = s.id AND NOT is_confirmed),
                    'manual_address_ids', ARRAY(
                        SELECT address_id FROM address_structures
                        WHERE structure_id = s.id AND matched_form_id IS NULL),
                    'perimeter_codes', ARRAY(
                        SELECT code FROM perimeters WHERE s.id = ANY(root_structure_ids))
                )
                FROM structures s WHERE s.id = :id
            """),
            {"id": structure_id},
        ).scalar()
        if snapshot is None:
            return None
        self._conn.execute(delete(structures).where(structures.c.id == structure_id))
        return cast(dict[str, JsonValue], snapshot)

    # ── structure_parents ─────────────────────────────────────────

    def get_ancestor_ids(self, structure_id: int) -> frozenset[int]:
        # Remontée récursive `child → parent` à travers `structure_parents`. Le résultat est sans `structure_id` lui-même.
        stmt = text(
            """
            WITH RECURSIVE ancestors(id) AS (
                SELECT parent_id FROM structure_parents
                WHERE child_id = :sid
                UNION
                SELECT sr.parent_id FROM structure_parents sr
                JOIN ancestors a ON a.id = sr.child_id
            )
            SELECT id FROM ancestors
            """
        ).bindparams(bindparam("sid", structure_id))
        result = self._conn.execute(stmt)
        return frozenset(row[0] for row in result)

    def create_tutelle(
        self,
        *,
        parent_id: int,
        child_id: int,
    ) -> StructureTutelleRow | None:
        stmt = (
            pg_insert(structure_parents)
            .values(parent_id=parent_id, child_id=child_id)
            .on_conflict_do_nothing(index_elements=["parent_id", "child_id"])
            .returning(
                structure_parents.c.id,
                structure_parents.c.parent_id,
                structure_parents.c.child_id,
            )
        )
        result = self._conn.execute(stmt)
        row = result.first()
        return cast(StructureTutelleRow, dict(row._mapping)) if row else None

    def delete_tutelle(self, tutelle_id: int) -> StructureTutelleDeletedRow | None:
        stmt = (
            delete(structure_parents)
            .where(structure_parents.c.id == tutelle_id)
            .returning(
                structure_parents.c.parent_id,
                structure_parents.c.child_id,
            )
        )
        result = self._conn.execute(stmt)
        row = result.first()
        return cast(StructureTutelleDeletedRow, dict(row._mapping)) if row else None

    # ── structure_name_forms ───────────────────────────────────────

    def find_name_form(self, form_id: int) -> StructureNameFormRow | None:
        result = self._conn.execute(
            select(*_NAME_FORM_COLUMNS).where(structure_name_forms.c.id == form_id)
        )
        row = result.first()
        return cast(StructureNameFormRow, dict(row._mapping)) if row else None

    def create_name_form(
        self,
        *,
        structure_id: int,
        form_text_normalized: str,
        is_word_boundary: bool,
        is_excluding: bool,
        requires_context_of: list[int] | None,
    ) -> StructureNameFormRow:
        stmt = (
            structure_name_forms.insert()
            .values(
                structure_id=structure_id,
                form_text=form_text_normalized,
                is_word_boundary=is_word_boundary,
                is_excluding=is_excluding,
                requires_context_of=requires_context_of or None,
            )
            .returning(*_NAME_FORM_COLUMNS)
        )
        result = self._conn.execute(stmt)
        return cast(StructureNameFormRow, dict(result.one()._mapping))

    def update_name_form_fields(
        self, form_id: int, fields: StructureNameFormUpdateFields
    ) -> StructureNameFormRow:
        stmt = (
            update(structure_name_forms)
            .where(structure_name_forms.c.id == form_id)
            .values(**fields)
            .returning(*_NAME_FORM_COLUMNS)
        )
        row = self._conn.execute(stmt).one_or_none()
        if row is None:
            raise NotFoundError(f"Forme {form_id} introuvable")
        return cast(StructureNameFormRow, dict(row._mapping))

    def delete_name_form(self, form_id: int) -> StructureNameFormDeletedRow | None:
        stmt = (
            delete(structure_name_forms)
            .where(structure_name_forms.c.id == form_id)
            .returning(
                structure_name_forms.c.structure_id,
                structure_name_forms.c.form_text,
            )
        )
        result = self._conn.execute(stmt)
        row = result.first()
        return cast(StructureNameFormDeletedRow, dict(row._mapping)) if row else None
