"""Service Structures — écritures sur l'agrégat Structure, transaction-agnostiques.

Couvre les tables `structures`, `structure_relations` et `structure_name_forms`. La validation du JSONB `api_ids` se fait à la frontière infra (repo) : tout chemin d'écriture y passe, la validation s'y applique uniformément.
"""

from typing import cast

from application.audit_log import emit_event
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.structure_repository import (
    StructureNameFormRow,
    StructureNameFormUpdateFields,
    StructureRelationRow,
    StructureRepository,
    StructureRow,
)
from domain.errors import NotFoundError, ValidationError
from domain.normalize import normalize_text
from domain.structures.name_forms import is_short_form
from domain.structures.relations import check_can_create_relation, require_known_relation_type
from domain.structures.structure import Structure
from domain.types import JsonValue

# ── structures : charger-muter-sauver l'agrégat ────────────────────


def _as_str(value: JsonValue | None) -> str | None:
    """Valeur de champ ramenée à `str | None` : les champs de structure (nom, acronyme, type, identifiants) sont textuels ; toute autre forme vaut « non fourni »."""
    return value if isinstance(value, str) else None


def _to_row(structure: Structure) -> StructureRow:
    """Sérialise l'agrégat vers la ligne de réponse : `structure_type` sous l'alias `type`, VOs `ror_id`/`hal_collection` rendus en chaînes canoniques."""
    return {
        "id": cast("int", structure.id),
        "code": structure.code,
        "name": structure.name,
        "acronym": structure.acronym,
        "type": structure.structure_type.value,
        "ror_id": structure.ror_id.value if structure.ror_id else None,
        "rnsr_id": structure.rnsr_id,
        "hal_collection": structure.hal_collection.value if structure.hal_collection else None,
        "api_ids": structure.api_ids,
    }


def create_structure(
    *,
    code: str,
    name: str,
    acronym: str | None = None,
    type: str,
    ror_id: str | None = None,
    rnsr_id: str | None = None,
    hal_collection: str | None = None,
    api_ids: dict[str, str | list[str]] | None = None,
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> StructureRow:
    """Crée une structure. Retourne la ligne insérée. Lève `ValidationError` si un champ est invalide (`type` hors énumération, `ror_id`/`hal_collection` mal formés, `api_ids` non conforme)."""
    structure = Structure.create(
        code=code,
        name=name,
        type=type,
        acronym=acronym,
        ror_id=ror_id,
        rnsr_id=rnsr_id,
        hal_collection=hal_collection,
        api_ids=api_ids,
    )
    structure.id = repo.add(structure)
    emit_event(
        audit_repo,
        "structure.created",
        "structure",
        structure.id,
        {"code": code, "name": name, "type": type},
    )
    return _to_row(structure)


def update_structure(
    structure_id: int,
    *,
    fields: dict[str, JsonValue],
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> StructureRow:
    """Met à jour une structure. Charge l'agrégat, applique les champs fournis (validés), persiste.

    Lève `NotFoundError` si la structure n'existe pas, `ValidationError` si aucun champ valide n'est fourni ou si une valeur est invalide.
    """
    structure = repo.find_by_id(structure_id)
    if structure is None:
        raise NotFoundError(f"Structure {structure_id} introuvable")

    api_ids = fields.get("api_ids")
    applied = structure.apply(
        name=_as_str(fields.get("name")),
        acronym=_as_str(fields.get("acronym")),
        type=_as_str(fields.get("type")),
        ror_id=_as_str(fields.get("ror_id")),
        rnsr_id=_as_str(fields.get("rnsr_id")),
        hal_collection=_as_str(fields.get("hal_collection")),
        api_ids=cast("dict[str, str | list[str]]", api_ids) if isinstance(api_ids, dict) else None,
    )
    if not applied:
        raise ValidationError("Aucun champ à mettre à jour")

    repo.save(structure)
    emit_event(
        audit_repo,
        "structure.updated",
        "structure",
        structure_id,
        {"fields": sorted(applied)},
    )
    return _to_row(structure)


def delete_structure(
    structure_id: int,
    *,
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Supprime une structure. Lève NotFoundError si elle n'existe pas.

    Cascade DB via FK `ON DELETE CASCADE` sur `authorship_structures` et `source_authorship_structures`. Le nettoyage du périmètre (retrait des racines de `perimeters.root_structure_ids`, rematérialisation de la clôture) relève du command handler.
    """
    row = repo.delete_structure(structure_id)
    if not row:
        raise NotFoundError(f"Structure {structure_id} introuvable")
    emit_event(
        audit_repo,
        "structure.deleted",
        "structure",
        structure_id,
        {"code": row["code"], "name": row["name"]},
    )


# ── structure_relations ───────────────────────────────────────────


def create_relation(
    *,
    parent_id: int,
    child_id: int,
    relation_type: str,
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> StructureRelationRow | None:
    """Crée une relation. Retourne la ligne insérée, ou None si elle existait déjà.

    Lève `ValidationError` si `relation_type` n'appartient pas à `StructureRelationType`, ou si la relation viole l'invariant de graphe (auto-référence `parent_id == child_id` ou cycle : `child_id` est déjà un ancêtre de `parent_id`). Les ancêtres sont préchargés via `repo.get_ancestor_ids` et la validation est déléguée au domaine.
    """
    require_known_relation_type(relation_type)
    check_can_create_relation(
        parent_id=parent_id,
        child_id=child_id,
        ancestors_of_parent=repo.get_ancestor_ids(parent_id),
    )
    row = repo.create_relation(
        parent_id=parent_id,
        child_id=child_id,
        relation_type=relation_type,
    )
    if row is not None:
        emit_event(
            audit_repo,
            "structure_relation.created",
            "structure",
            parent_id,
            {
                "relation_id": row["id"],
                "parent_id": parent_id,
                "child_id": child_id,
                "relation_type": relation_type,
            },
        )
    return row


def delete_relation(
    relation_id: int,
    *,
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Supprime une relation. Lève NotFoundError si elle n'existe pas."""
    row = repo.delete_relation(relation_id)
    if not row:
        raise NotFoundError(f"Relation {relation_id} introuvable")
    emit_event(
        audit_repo,
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


def create_name_form(
    *,
    structure_id: int,
    form_text: str,
    is_word_boundary: bool = False,
    is_excluding: bool = False,
    requires_context_of: list[int] | None = None,
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> StructureNameFormRow:
    """Crée une forme de nom. Retourne la ligne insérée."""
    form_text_normalized = normalize_text(form_text)
    row = repo.create_name_form(
        structure_id=structure_id,
        form_text_normalized=form_text_normalized,
        # Forme courte ⇒ frontière de mot forcée (invariant verrouillé par une CHECK).
        is_word_boundary=is_word_boundary or is_short_form(form_text_normalized),
        is_excluding=is_excluding,
        requires_context_of=requires_context_of,
    )
    emit_event(
        audit_repo,
        "structure_name_form.created",
        "structure",
        structure_id,
        {"form_id": row["id"], "form_text": row["form_text"]},
    )
    return row


def update_name_form(
    form_id: int,
    *,
    fields: dict[str, JsonValue],
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> StructureNameFormRow:
    """Met à jour une forme de nom. Retourne la ligne modifiée.

    Lève NotFoundError si la forme n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    existing = repo.find_name_form(form_id)
    if existing is None:
        raise NotFoundError(f"Forme {form_id} introuvable")

    update_fields: StructureNameFormUpdateFields = {}

    form_text = fields.get("form_text")
    if isinstance(form_text, str):
        update_fields["form_text"] = normalize_text(form_text)
    is_word_boundary = fields.get("is_word_boundary")
    if isinstance(is_word_boundary, bool):
        update_fields["is_word_boundary"] = is_word_boundary
    is_excluding = fields.get("is_excluding")
    if isinstance(is_excluding, bool):
        update_fields["is_excluding"] = is_excluding
    requires_context_of = fields.get("requires_context_of")
    if isinstance(requires_context_of, list):
        update_fields["requires_context_of"] = cast("list[int]", requires_context_of) or None

    if not update_fields:
        raise ValidationError("Aucun champ à mettre à jour")

    # Forme courte ⇒ frontière de mot forcée (invariant verrouillé par une CHECK).
    # Texte effectif : le nouveau s'il est fourni, sinon celui déjà en base.
    effective_form_text = update_fields.get("form_text", existing["form_text"])
    if is_short_form(effective_form_text):
        update_fields["is_word_boundary"] = True

    row = repo.update_name_form_fields(form_id, update_fields)
    emit_event(
        audit_repo,
        "structure_name_form.updated",
        "structure",
        existing["structure_id"],
        {"form_id": form_id, "fields": sorted(update_fields)},
    )
    return row


def delete_name_form(
    form_id: int,
    *,
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Supprime une forme de nom. Lève NotFoundError si elle n'existe pas."""
    row = repo.delete_name_form(form_id)
    if not row:
        raise NotFoundError(f"Forme {form_id} introuvable")
    emit_event(
        audit_repo,
        "structure_name_form.deleted",
        "structure",
        row["structure_id"],
        {"form_id": form_id, "form_text": row["form_text"]},
    )
