"""Repository PostgreSQL de l'entité Structure : structures, tutelles et formes de nom."""

from typing import NamedTuple, cast

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Connection, Text, bindparam, cast as sql_cast, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from application.ports.repositories.structure_repository import (
    StructureNameFormDeletedRow,
    StructureNameFormRow,
    StructureNameFormUpdateFields,
    StructureRepository,
    StructureTutelleDeletedRow,
    StructureTutelleRow,
)
from domain.errors import NotFoundError, ValidationError
from domain.structures.identifiers import HalCollection, RorId
from domain.structures.name_forms import StructureNameForm
from domain.structures.structure import Structure, StructureType
from domain.types import JsonValue
from infrastructure.db.rows import row_as, rows_as
from infrastructure.db.scalars import scalar_int
from infrastructure.db.tables import (
    structure_name_forms,
    structure_parents,
    structures,
)
from infrastructure.jsonb_models.structure import StructureApiIds

# Colonnes de `structure_name_forms` renvoyées par create / update / get (RETURNING ou SELECT).
_NAME_FORM_COLUMNS = (
    structure_name_forms.c.id,
    structure_name_forms.c.structure_id,
    structure_name_forms.c.form_text,
    structure_name_forms.c.created_at,
    structure_name_forms.c.is_word_boundary,
    structure_name_forms.c.requires_context_of,
    structure_name_forms.c.is_excluding,
)


class _StructureNameFormRow(NamedTuple):
    """Projection SQL sur `structure_name_forms` (find_by_id de l'aggregate Structure)."""

    form_text: str
    is_word_boundary: bool
    is_excluding: bool
    requires_context_of: list[int] | None


class _StructureRow(NamedTuple):
    """Projection SQL `find_by_id` sur `structures`."""

    id: int
    code: str
    name: str
    acronym: str | None
    structure_type: str
    ror_id: str | None
    rnsr_id: str | None
    hal_collection: str | None
    api_ids: dict[str, list[str]] | None


def _structure_name_form_from_row(row: _StructureNameFormRow) -> StructureNameForm:
    """Forme de nom de domaine d'une ligne de `structure_name_forms`."""
    return StructureNameForm(
        form_text=row.form_text,
        is_word_boundary=row.is_word_boundary,
        is_excluding=row.is_excluding,
        requires_context_of=tuple(row.requires_context_of or ()),
    )


def _structure_from_row(row: _StructureRow, name_forms: tuple[StructureNameForm, ...]) -> Structure:
    """Structure de domaine d'une ligne de `structures`, avec ses formes de nom, chargées à part par `find_by_id`.

    Le ROR et la collection HAL se lisent en strict : une valeur mal normalisée en base lève `ValidationError`, et signale une corruption.
    """
    return Structure(
        id=row.id,
        code=row.code,
        name=row.name,
        structure_type=StructureType(row.structure_type),
        acronym=row.acronym,
        ror_id=RorId(row.ror_id) if row.ror_id else None,
        rnsr_id=row.rnsr_id,
        hal_collection=HalCollection(row.hal_collection) if row.hal_collection else None,
        api_ids=row.api_ids,
        name_forms=name_forms,
    )


def _normalize_api_ids(raw: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
    """Forme normalisée de `api_ids` (`StructureApiIds`), ou `None` pour une entrée vide. Lève `ValidationError` si le schéma est violé.

    La validation se fait dans le repository : toute écriture y passe, y compris celle des scripts qui contournent la couche application.
    """
    if not raw:
        return None
    try:
        return StructureApiIds(**raw).to_dict() or None
    except PydanticValidationError as e:
        raise ValidationError(f"api_ids invalide : {e}") from e


class PgStructureRepository(StructureRepository):
    """Accès PostgreSQL sync à l'entité Structure."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Chargement ─────────────────────────────────────────────────

    def find_by_id(self, structure_id: int) -> Structure | None:
        row = self._conn.execute(
            select(
                structures.c.id,
                structures.c.code,
                structures.c.name,
                structures.c.acronym,
                sql_cast(structures.c.structure_type, Text).label("structure_type"),
                structures.c.ror_id,
                structures.c.rnsr_id,
                structures.c.hal_collection,
                structures.c.api_ids,
            ).where(structures.c.id == structure_id)
        ).first()
        if row is None:
            return None
        name_form_result = self._conn.execute(
            select(
                structure_name_forms.c.form_text,
                structure_name_forms.c.is_word_boundary,
                structure_name_forms.c.is_excluding,
                structure_name_forms.c.requires_context_of,
            ).where(structure_name_forms.c.structure_id == structure_id)
        )
        name_forms = tuple(
            _structure_name_form_from_row(name_form)
            for name_form in rows_as(_StructureNameFormRow, name_form_result)
        )
        return _structure_from_row(row_as(_StructureRow, row), name_forms)

    # ── structures ─────────────────────────────────────────────────

    def add(self, structure: Structure) -> int:
        """Insère une structure et renvoie son id. `api_ids` est validé, et posé sous sa forme normalisée sur l'entité."""
        structure.api_ids = _normalize_api_ids(structure.api_ids)
        return scalar_int(
            self._conn.execute(
                structures.insert()
                .values(
                    code=structure.code,
                    name=structure.name,
                    structure_type=structure.structure_type.value,
                    acronym=structure.acronym,
                    ror_id=structure.ror_id.value if structure.ror_id else None,
                    rnsr_id=structure.rnsr_id,
                    hal_collection=structure.hal_collection.value
                    if structure.hal_collection
                    else None,
                    api_ids=structure.api_ids,
                )
                .returning(structures.c.id)
            )
        )

    def save(self, structure: Structure) -> None:
        """Écrit les champs modifiables d'une structure chargée ; le code reste. `api_ids` est validé. Lève `NotFoundError` si l'id est absent."""
        structure.api_ids = _normalize_api_ids(structure.api_ids)
        result = self._conn.execute(
            update(structures)
            .where(structures.c.id == structure.id)
            .values(
                name=structure.name,
                structure_type=structure.structure_type.value,
                acronym=structure.acronym,
                ror_id=structure.ror_id.value if structure.ror_id else None,
                rnsr_id=structure.rnsr_id,
                hal_collection=structure.hal_collection.value if structure.hal_collection else None,
                api_ids=structure.api_ids,
            )
        )
        if result.rowcount == 0:
            raise NotFoundError(f"Structure {structure.id} introuvable")

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
