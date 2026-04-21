"""
Service Structures — orchestrateur des opérations sur `structures`,
`structure_relations`, `structure_name_forms`.

Le SQL vit dans `infrastructure/repositories/structure_repository.py`.
Les routers passent par ces fonctions pour toute écriture. Les lectures
restent autorisées dans les routers (convention du projet).
"""

from typing import Any

from psycopg.types.json import Jsonb as Json
from pydantic import ValidationError as PydanticValidationError

from application.audit import async_emit_event
from domain.errors import NotFoundError, ValidationError
from domain.normalize import normalize_text
from domain.ports.structure_repository import AsyncStructureRepository
from domain.structure import StructureApiIds


def _validate_api_ids(raw: dict | None) -> dict | None:
    """Valide et normalise `api_ids` via le modèle domaine StructureApiIds.

    - Entrée : dict brut (côté API admin) ou None.
    - Sortie : dict canonique prêt pour JSONB, ou None si l'entrée est vide/None.
    - Lève ValidationError métier si le schéma est violé.
    """
    if not raw:
        return None
    try:
        return StructureApiIds(**raw).to_dict() or None
    except PydanticValidationError as e:
        raise ValidationError(f"api_ids invalide : {e}") from e


# ── Mapping des champs UI → colonnes SQL pour la table structures ──
_STRUCTURE_FIELD_MAP = {
    "name": "name",
    "acronym": "acronym",
    "type": "structure_type",
    "ror_id": "ror_id",
    "rnsr_id": "rnsr_id",
    "hal_collection": "hal_collection",
}


# ── structures ────────────────────────────────────────────────────


async def create_structure(
    cur: Any,
    *,
    code: str,
    name: str,
    acronym: str | None = None,
    type: str,
    ror_id: str | None = None,
    rnsr_id: str | None = None,
    hal_collection: str | None = None,
    api_ids: dict | None = None,
    repo: AsyncStructureRepository,
) -> dict:
    """Crée une structure. Retourne la ligne insérée (dict)."""
    return await repo.create_structure(
        code=code,
        name=name,
        acronym=acronym,
        type=type,
        ror_id=ror_id,
        rnsr_id=rnsr_id,
        hal_collection=hal_collection,
        api_ids=_validate_api_ids(api_ids),
    )


async def update_structure(
    cur: Any, structure_id: int, *, fields: dict, repo: AsyncStructureRepository
) -> dict:
    """Met à jour une structure. Retourne la ligne modifiée.

    Lève NotFoundError si la structure n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    if not await repo.structure_exists(structure_id):
        raise NotFoundError(f"Structure {structure_id} introuvable")

    sql_fragments: list[str] = []
    params: list = []
    for field_name, col_name in _STRUCTURE_FIELD_MAP.items():
        val = fields.get(field_name)
        if val is not None:
            sql_fragments.append(f"{col_name} = %s")
            params.append(val)

    if "api_ids" in fields and fields["api_ids"] is not None:
        validated = _validate_api_ids(fields["api_ids"])
        sql_fragments.append("api_ids = %s")
        params.append(Json(validated) if validated else None)

    if not sql_fragments:
        raise ValidationError("Aucun champ à mettre à jour")

    return await repo.update_structure_fields(structure_id, sql_fragments, params)


async def delete_structure(
    cur: Any, structure_id: int, *, repo: AsyncStructureRepository
) -> None:
    """Supprime une structure. Lève NotFoundError si elle n'existe pas."""
    row = await repo.delete_structure(structure_id)
    if not row:
        raise NotFoundError(f"Structure {structure_id} introuvable")
    await async_emit_event(
        cur,
        "structure.deleted",
        "structure",
        structure_id,
        {"code": row["code"], "name": row["name"]},
    )


# ── structure_relations ───────────────────────────────────────────


async def create_relation(
    cur: Any,
    *,
    parent_id: int,
    child_id: int,
    relation_type: str,
    repo: AsyncStructureRepository,
) -> dict | None:
    """Crée une relation. Retourne la ligne insérée, ou None si elle existait déjà."""
    return await repo.create_relation(
        parent_id=parent_id,
        child_id=child_id,
        relation_type=relation_type,
    )


async def delete_relation(
    cur: Any, relation_id: int, *, repo: AsyncStructureRepository
) -> None:
    """Supprime une relation. Lève NotFoundError si elle n'existe pas."""
    row = await repo.delete_relation(relation_id)
    if not row:
        raise NotFoundError(f"Relation {relation_id} introuvable")
    await async_emit_event(
        cur,
        "structure_relation.deleted",
        "structure",
        row["parent_id"],
        {
            "relation_id": relation_id,
            "parent_id": row["parent_id"],
            "child_id": row["child_id"],
            "relation_type": row["relation_type"],
        },
    )


# ── structure_name_forms ──────────────────────────────────────────


async def create_name_form(
    cur: Any,
    *,
    structure_id: int,
    form_text: str,
    is_word_boundary: bool = False,
    is_excluding: bool = False,
    requires_context_of: list | None = None,
    repo: AsyncStructureRepository,
) -> dict:
    """Crée une forme de nom. Retourne la ligne insérée."""
    return await repo.create_name_form(
        structure_id=structure_id,
        form_text_normalized=normalize_text(form_text),
        is_word_boundary=is_word_boundary,
        is_excluding=is_excluding,
        requires_context_of=requires_context_of,
    )


async def update_name_form(
    cur: Any, form_id: int, *, fields: dict, repo: AsyncStructureRepository
) -> dict:
    """Met à jour une forme de nom. Retourne la ligne modifiée.

    Lève NotFoundError si la forme n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    if not await repo.name_form_exists(form_id):
        raise NotFoundError(f"Forme {form_id} introuvable")

    sql_fragments: list[str] = []
    params: list = []

    if fields.get("form_text") is not None:
        sql_fragments.append("form_text = %s")
        params.append(normalize_text(fields["form_text"]))
    if fields.get("is_word_boundary") is not None:
        sql_fragments.append("is_word_boundary = %s")
        params.append(fields["is_word_boundary"])
    if fields.get("is_excluding") is not None:
        sql_fragments.append("is_excluding = %s")
        params.append(fields["is_excluding"])
    if fields.get("requires_context_of") is not None:
        sql_fragments.append("requires_context_of = %s")
        params.append(fields["requires_context_of"] or None)

    if not sql_fragments:
        raise ValidationError("Aucun champ à mettre à jour")

    return await repo.update_name_form_fields(form_id, sql_fragments, params)


async def delete_name_form(cur: Any, form_id: int, *, repo: AsyncStructureRepository) -> None:
    """Supprime une forme de nom. Lève NotFoundError si elle n'existe pas."""
    row = await repo.delete_name_form(form_id)
    if not row:
        raise NotFoundError(f"Forme {form_id} introuvable")
    await async_emit_event(
        cur,
        "structure_name_form.deleted",
        "structure",
        row["structure_id"],
        {"form_id": form_id, "form_text": row["form_text"]},
    )
