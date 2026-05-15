"""Adapter PostgreSQL sync pour les 3 tables du concept Structure."""

from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import Connection, Text, bindparam, cast, delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from domain.errors import ValidationError
from infrastructure.db.jsonb_models.structure import StructureApiIds
from infrastructure.db.tables import (
    structure_name_forms,
    structure_relations,
    structures,
)


def _normalize_api_ids(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Valide et normalise `api_ids` via le modèle JSONB StructureApiIds.

    - Entrée : dict brut (côté API admin) ou None.
    - Sortie : dict canonique prêt JSONB, ou None si l'entrée est
      vide/None.
    - Lève `domain.errors.ValidationError` si le schéma est violé.

    La validation vit côté repo (frontière infra→DB) : tout chemin
    d'écriture passe par ici, y compris les scripts CLI qui
    court-circuitent la couche application.
    """
    if not raw:
        return None
    try:
        return StructureApiIds(**raw).to_dict() or None
    except PydanticValidationError as e:
        raise ValidationError(f"api_ids invalide : {e}") from e


def _structure_returning_columns() -> list:
    """Colonnes RETURNING pour les opérations create/update sur structures."""
    return [
        structures.c.id,
        structures.c.code,
        structures.c.name,
        structures.c.acronym,
        cast(structures.c.structure_type, Text).label("type"),
        structures.c.ror_id,
        structures.c.rnsr_id,
        structures.c.hal_collection,
        structures.c.api_ids,
    ]


class PgStructureRepository:
    """Accès PostgreSQL sync à l'agrégat Structure."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── structures ─────────────────────────────────────────────────

    def structure_exists(self, structure_id: int) -> bool:
        result = self._conn.execute(select(structures.c.id).where(structures.c.id == structure_id))
        return result.first() is not None

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
        stmt = (
            structures.insert()
            .values(
                code=code,
                name=name,
                acronym=acronym,
                structure_type=type,
                ror_id=ror_id,
                rnsr_id=rnsr_id,
                hal_collection=hal_collection,
                api_ids=_normalize_api_ids(api_ids),
            )
            .returning(*_structure_returning_columns())
        )
        result = self._conn.execute(stmt)
        return dict(result.one()._mapping)

    def update_structure_fields(self, structure_id: int, fields: dict) -> dict:
        if "api_ids" in fields:
            fields = {**fields, "api_ids": _normalize_api_ids(fields["api_ids"])}
        stmt = (
            update(structures)
            .where(structures.c.id == structure_id)
            .values(**fields)
            .returning(*_structure_returning_columns())
        )
        result = self._conn.execute(stmt)
        return dict(result.one()._mapping)

    def delete_structure(self, structure_id: int) -> dict | None:
        stmt = (
            delete(structures)
            .where(structures.c.id == structure_id)
            .returning(structures.c.code, structures.c.name)
        )
        result = self._conn.execute(stmt)
        row = result.first()
        return dict(row._mapping) if row else None

    # ── structure_relations ────────────────────────────────────────

    def get_ancestor_ids(self, structure_id: int) -> frozenset[int]:
        # Remontée récursive `child → parent` à travers `structure_relations`,
        # toutes `relation_type` confondues (un cycle est un cycle quel que
        # soit le type d'arête). `structure_id` lui-même est exclu du résultat.
        stmt = text(
            """
            WITH RECURSIVE ancestors(id) AS (
                SELECT parent_id FROM structure_relations
                WHERE child_id = :sid
                UNION
                SELECT sr.parent_id FROM structure_relations sr
                JOIN ancestors a ON a.id = sr.child_id
            )
            SELECT id FROM ancestors
            """
        ).bindparams(bindparam("sid", structure_id))
        result = self._conn.execute(stmt)
        return frozenset(row[0] for row in result)

    def create_relation(
        self,
        *,
        parent_id: int,
        child_id: int,
        relation_type: str,
    ) -> dict | None:
        stmt = (
            pg_insert(structure_relations)
            .values(parent_id=parent_id, child_id=child_id, relation_type=relation_type)
            .on_conflict_do_nothing(index_elements=["parent_id", "child_id", "relation_type"])
            .returning(
                structure_relations.c.id,
                structure_relations.c.parent_id,
                structure_relations.c.child_id,
                structure_relations.c.relation_type,
            )
        )
        result = self._conn.execute(stmt)
        row = result.first()
        return dict(row._mapping) if row else None

    def delete_relation(self, relation_id: int) -> dict | None:
        stmt = (
            delete(structure_relations)
            .where(structure_relations.c.id == relation_id)
            .returning(
                structure_relations.c.parent_id,
                structure_relations.c.child_id,
                structure_relations.c.relation_type,
            )
        )
        result = self._conn.execute(stmt)
        row = result.first()
        return dict(row._mapping) if row else None

    # ── structure_name_forms ───────────────────────────────────────

    def name_form_exists(self, form_id: int) -> bool:
        result = self._conn.execute(
            select(structure_name_forms.c.id).where(structure_name_forms.c.id == form_id)
        )
        return result.first() is not None

    def create_name_form(
        self,
        *,
        structure_id: int,
        form_text_normalized: str,
        is_word_boundary: bool,
        is_excluding: bool,
        requires_context_of: list | None,
    ) -> dict:
        stmt = (
            structure_name_forms.insert()
            .values(
                structure_id=structure_id,
                form_text=form_text_normalized,
                is_word_boundary=is_word_boundary,
                is_excluding=is_excluding,
                requires_context_of=requires_context_of or None,
            )
            .returning(
                structure_name_forms.c.id,
                structure_name_forms.c.structure_id,
                structure_name_forms.c.form_text,
                structure_name_forms.c.created_at,
                structure_name_forms.c.is_word_boundary,
                structure_name_forms.c.requires_context_of,
                structure_name_forms.c.is_excluding,
            )
        )
        result = self._conn.execute(stmt)
        return dict(result.one()._mapping)

    def update_name_form_fields(self, form_id: int, fields: dict) -> dict:
        stmt = (
            update(structure_name_forms)
            .where(structure_name_forms.c.id == form_id)
            .values(**fields)
            .returning(
                structure_name_forms.c.id,
                structure_name_forms.c.structure_id,
                structure_name_forms.c.form_text,
                structure_name_forms.c.created_at,
                structure_name_forms.c.is_word_boundary,
                structure_name_forms.c.requires_context_of,
                structure_name_forms.c.is_excluding,
            )
        )
        result = self._conn.execute(stmt)
        return dict(result.one()._mapping)

    def delete_name_form(self, form_id: int) -> dict | None:
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
        return dict(row._mapping) if row else None
