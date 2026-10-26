"""Service Structures — écritures sur l'agrégat Structure.

Couvre les tables `structures`, `structure_parents` et `structure_name_forms`. La validation du JSONB `api_ids` se fait à la frontière infra (repo) : tout chemin d'écriture y passe, la validation s'y applique uniformément.
"""

from application.audit_log import emit_event
from application.ports.pipeline.perimeter_structures import PerimeterStructures
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.structure_repository import (
    NameFormCreate,
    NameFormUpdate,
    StructureCreate,
    StructureNameFormRow,
    StructureNameFormUpdateFields,
    StructureRepository,
    StructureTutelleRow,
    StructureUpdate,
)
from domain.errors import NotFoundError, ValidationError
from domain.normalize import normalize_text
from domain.structures.name_forms import is_short_form
from domain.structures.structure import Structure, StructureEdit
from domain.structures.tutelles import check_can_create_tutelle

# ── structures : charger-muter-sauver l'agrégat ────────────────────


def create_structure(create: StructureCreate, *, repo: StructureRepository) -> Structure:
    """Crée une structure et la rend. Lève `ValidationError` si un champ est invalide (`type` hors énumération, `ror_id`/`hal_collection` mal formés, `api_ids` non conforme)."""
    structure = Structure.create(
        code=create.code,
        name=create.name,
        structure_type=create.type,
        acronym=create.acronym,
        ror_id=create.ror_id,
        rnsr_id=create.rnsr_id,
        hal_collection=create.hal_collection,
        api_ids=create.api_ids,
    )
    structure.id = repo.add(structure)
    emit_event(
        "structure.created",
        "structure",
        structure.id,
        {"code": create.code, "name": create.name, "type": create.type},
    )
    return structure


def update_structure(
    structure_id: int,
    *,
    update: StructureUpdate,
    repo: StructureRepository,
) -> Structure:
    """Met à jour une structure. Charge l'agrégat, applique les champs fournis (validés), persiste. `null` efface un champ facultatif ; sur le nom ou le type, il vaut champ non fourni.

    Lève `NotFoundError` si la structure n'existe pas, `ValidationError` si aucun champ n'est fourni ou si une valeur est invalide.
    """
    structure = repo.find_by_id(structure_id)
    if structure is None:
        raise NotFoundError(f"Structure {structure_id} introuvable")

    applied = structure.apply(**_structure_edit(update))
    if not applied:
        raise ValidationError("Aucun champ à mettre à jour")

    repo.save(structure)
    emit_event(
        "structure.updated",
        "structure",
        structure_id,
        {"fields": sorted(applied)},
    )
    return structure


def _structure_edit(update: StructureUpdate) -> StructureEdit:
    """Champs fournis de `update`, sous la forme que l'agrégat reçoit."""
    provided = update.model_fields_set
    changes = StructureEdit()
    if "name" in provided and update.name is not None:
        changes["name"] = update.name
    if "type" in provided and update.type is not None:
        changes["structure_type"] = update.type
    if "acronym" in provided:
        changes["acronym"] = update.acronym
    if "ror_id" in provided:
        changes["ror_id"] = update.ror_id
    if "rnsr_id" in provided:
        changes["rnsr_id"] = update.rnsr_id
    if "hal_collection" in provided:
        changes["hal_collection"] = update.hal_collection
    if "api_ids" in provided:
        changes["api_ids"] = update.api_ids
    return changes


def delete_structure(
    structure_id: int,
    *,
    repo: StructureRepository,
    perimeter_repo: PerimeterRepository,
    perimeter_structures: PerimeterStructures,
) -> None:
    """Supprime une structure. Lève NotFoundError si elle n'existe pas.

    La base supprime en cascade ses formes de nom, ses tutelles et ses liens adresse-structure, confirmés compris (`ON DELETE CASCADE`). La structure quitte les racines de tout périmètre, puis la clôture des périmètres est recalculée : la structure et ses tutelles en modifient la descente.
    """
    snapshot = repo.delete_structure(structure_id)
    if snapshot is None:
        raise NotFoundError(f"Structure {structure_id} introuvable")
    perimeter_repo.remove_structure_from_all_perimeters(structure_id)
    perimeter_structures.refresh()
    # L'instantané garde ce que la cascade emporte : une suppression par erreur reste réparable à la main.
    emit_event("structure.deleted", "structure", structure_id, snapshot)


# ── structure_parents ────────────────────────────────────────────


def create_tutelle(
    *,
    parent_id: int,
    child_id: int,
    repo: StructureRepository,
    perimeter_structures: PerimeterStructures,
) -> StructureTutelleRow | None:
    """Crée une tutelle, puis recalcule la clôture des périmètres, dont une tutelle modifie la descente. Retourne la ligne insérée, ou None si elle existait déjà.

    Lève `ValidationError` si la tutelle viole l'invariant de graphe (auto-référence `parent_id == child_id` ou cycle : `child_id` est déjà un ancêtre de `parent_id`). Les ancêtres sont préchargés via `repo.get_ancestor_ids` et la validation est déléguée au domaine.
    """
    check_can_create_tutelle(
        parent_id=parent_id,
        child_id=child_id,
        ancestors_of_parent=repo.get_ancestor_ids(parent_id),
    )
    row = repo.create_tutelle(parent_id=parent_id, child_id=child_id)
    if row is not None:
        perimeter_structures.refresh()
        # Nom d'événement conservé : il est écrit dans `audit_log`, où l'historique le contient.
        emit_event(
            "structure_relation.created",
            "structure",
            parent_id,
            {"relation_id": row["id"], "parent_id": parent_id, "child_id": child_id},
        )
    return row


def delete_tutelle(
    tutelle_id: int,
    *,
    repo: StructureRepository,
    perimeter_structures: PerimeterStructures,
) -> None:
    """Supprime une tutelle, puis recalcule la clôture des périmètres. Lève NotFoundError si elle n'existe pas."""
    row = repo.delete_tutelle(tutelle_id)
    if not row:
        raise NotFoundError(f"Tutelle {tutelle_id} introuvable")
    perimeter_structures.refresh()
    emit_event(
        "structure_relation.deleted",
        "structure",
        row["parent_id"],
        {
            "relation_id": tutelle_id,
            "parent_id": row["parent_id"],
            "child_id": row["child_id"],
        },
    )


# ── structure_name_forms ──────────────────────────────────────────


def create_name_form(create: NameFormCreate, *, repo: StructureRepository) -> StructureNameFormRow:
    """Crée une forme de nom. Retourne la ligne insérée."""
    form_text_normalized = normalize_text(create.form_text)
    row = repo.create_name_form(
        structure_id=create.structure_id,
        form_text_normalized=form_text_normalized,
        # Forme courte ⇒ frontière de mot forcée (invariant verrouillé par une CHECK).
        is_word_boundary=create.is_word_boundary or is_short_form(form_text_normalized),
        is_excluding=create.is_excluding,
        requires_context_of=create.requires_context_of,
    )
    emit_event(
        "structure_name_form.created",
        "structure",
        create.structure_id,
        {"form_id": row["id"], "form_text": row["form_text"]},
    )
    return row


def update_name_form(
    form_id: int,
    *,
    update: NameFormUpdate,
    repo: StructureRepository,
) -> StructureNameFormRow:
    """Met à jour une forme de nom. Retourne la ligne modifiée. `null` sur `requires_context_of` efface le contexte ; sur un autre champ, il vaut champ non fourni.

    Lève NotFoundError si la forme n'existe pas, ValidationError si aucun champ n'est fourni.
    """
    existing = repo.find_name_form(form_id)
    if existing is None:
        raise NotFoundError(f"Forme {form_id} introuvable")

    provided = update.model_fields_set
    update_fields: StructureNameFormUpdateFields = {}
    if "form_text" in provided and update.form_text is not None:
        update_fields["form_text"] = normalize_text(update.form_text)
    if "is_word_boundary" in provided and update.is_word_boundary is not None:
        update_fields["is_word_boundary"] = update.is_word_boundary
    if "is_excluding" in provided and update.is_excluding is not None:
        update_fields["is_excluding"] = update.is_excluding
    if "requires_context_of" in provided:
        update_fields["requires_context_of"] = update.requires_context_of or None

    if not update_fields:
        raise ValidationError("Aucun champ à mettre à jour")

    # Forme courte ⇒ frontière de mot forcée (invariant verrouillé par une CHECK).
    # Texte effectif : le nouveau s'il est fourni, sinon celui déjà en base.
    effective_form_text = update_fields.get("form_text", existing["form_text"])
    if is_short_form(effective_form_text):
        update_fields["is_word_boundary"] = True

    row = repo.update_name_form_fields(form_id, update_fields)
    emit_event(
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
) -> None:
    """Supprime une forme de nom. Lève NotFoundError si elle n'existe pas."""
    row = repo.delete_name_form(form_id)
    if not row:
        raise NotFoundError(f"Forme {form_id} introuvable")
    emit_event(
        "structure_name_form.deleted",
        "structure",
        row["structure_id"],
        {"form_id": form_id, "form_text": row["form_text"]},
    )
