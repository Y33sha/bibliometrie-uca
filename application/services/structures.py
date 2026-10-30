"""Service des structures : écritures sur l'entité Structure, ses tutelles et ses formes de nom.

Le repository valide `api_ids` à chaque écriture.
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


def _structure_edit(update: StructureUpdate) -> StructureEdit:
    """Renvoie les champs fournis de `update`, sous la forme reçue par l'entité."""
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


class StructureService:
    """Écritures sur les structures, leurs tutelles et leurs formes de nom.

    Une suppression de structure ou un changement de tutelle recalcule les structures des périmètres (`PerimeterStructures`).
    """

    def __init__(
        self,
        *,
        structures: StructureRepository,
        perimeters: PerimeterRepository,
        perimeter_structures: PerimeterStructures,
    ) -> None:
        self._structures = structures
        self._perimeters = perimeters
        self._perimeter_structures = perimeter_structures

    # ── Structures ──

    def create_structure(self, create: StructureCreate) -> Structure:
        """Crée une structure et la renvoie.

        Raises:
            ValidationError: champ invalide (`type` hors énumération, `ror_id` ou `hal_collection` mal formé, `api_ids` non conforme).
        """
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
        structure.id = self._structures.add(structure)
        emit_event(
            "structure.created",
            "structure",
            structure.id,
            {"code": create.code, "name": create.name, "type": create.type},
        )
        return structure

    def update_structure(self, structure_id: int, update: StructureUpdate) -> Structure:
        """Applique les champs fournis à la structure et l'enregistre. `null` efface un champ facultatif, et vaut champ non fourni sur le nom ou le type.

        Raises:
            NotFoundError: structure introuvable.
            ValidationError: aucun champ fourni, ou valeur invalide.
        """
        structure = self._structures.find_by_id(structure_id)
        if structure is None:
            raise NotFoundError(f"Structure {structure_id} introuvable")

        applied = structure.apply(**_structure_edit(update))
        if not applied:
            raise ValidationError("Aucun champ à mettre à jour")

        self._structures.save(structure)
        emit_event(
            "structure.updated",
            "structure",
            structure_id,
            {"fields": sorted(applied)},
        )
        return structure

    def delete_structure(self, structure_id: int) -> None:
        """Supprime une structure. Lève `NotFoundError` si elle n'existe pas.

        La base supprime en cascade ses formes de nom, ses tutelles et ses liens adresse-structure, confirmés compris (`ON DELETE CASCADE`). La structure est retirée des racines de tout périmètre, puis les structures des périmètres sont recalculées.
        """
        snapshot = self._structures.delete_structure(structure_id)
        if snapshot is None:
            raise NotFoundError(f"Structure {structure_id} introuvable")
        self._perimeters.remove_structure_from_all_perimeters(structure_id)
        self._perimeter_structures.refresh()
        # L'instantané contient les lignes supprimées en cascade. Une suppression par erreur reste donc réparable à la main.
        emit_event("structure.deleted", "structure", structure_id, snapshot)

    # ── Tutelles (structure_parents) ──

    def create_tutelle(self, *, parent_id: int, child_id: int) -> StructureTutelleRow | None:
        """Crée une tutelle, puis recalcule les structures des périmètres. Renvoie la ligne insérée, ou `None` si elle existait déjà.

        Raises:
            ValidationError: structure tutelle d'elle-même, ou cycle (l'enfant est déjà un ancêtre du parent).
        """
        check_can_create_tutelle(
            parent_id=parent_id,
            child_id=child_id,
            ancestors_of_parent=self._structures.get_ancestor_ids(parent_id),
        )
        row = self._structures.create_tutelle(parent_id=parent_id, child_id=child_id)
        if row is not None:
            self._perimeter_structures.refresh()
            emit_event(
                "structure_tutelle.created",
                "structure",
                parent_id,
                {"tutelle_id": row["id"], "parent_id": parent_id, "child_id": child_id},
            )
        return row

    def delete_tutelle(self, tutelle_id: int) -> None:
        """Supprime une tutelle, puis recalcule les structures des périmètres. Lève `NotFoundError` si elle n'existe pas."""
        row = self._structures.delete_tutelle(tutelle_id)
        if not row:
            raise NotFoundError(f"Tutelle {tutelle_id} introuvable")
        self._perimeter_structures.refresh()
        emit_event(
            "structure_tutelle.deleted",
            "structure",
            row["parent_id"],
            {
                "tutelle_id": tutelle_id,
                "parent_id": row["parent_id"],
                "child_id": row["child_id"],
            },
        )

    # ── Formes de nom (structure_name_forms) ──

    def create_name_form(self, create: NameFormCreate) -> StructureNameFormRow:
        """Crée une forme de nom et renvoie la ligne insérée."""
        form_text_normalized = normalize_text(create.form_text)
        row = self._structures.create_name_form(
            structure_id=create.structure_id,
            form_text_normalized=form_text_normalized,
            # Une forme courte impose la frontière de mot. Une contrainte CHECK garantit l'invariant.
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

    def update_name_form(self, form_id: int, update: NameFormUpdate) -> StructureNameFormRow:
        """Met à jour une forme de nom et renvoie la ligne modifiée. `null` efface `requires_context_of`, et vaut champ non fourni sur un autre champ.

        Raises:
            NotFoundError: forme introuvable.
            ValidationError: aucun champ fourni.
        """
        existing = self._structures.find_name_form(form_id)
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

        # Une forme courte impose la frontière de mot. Une contrainte CHECK garantit l'invariant.
        # Texte effectif : le nouveau s'il est fourni, sinon celui déjà en base.
        effective_form_text = update_fields.get("form_text", existing["form_text"])
        if is_short_form(effective_form_text):
            update_fields["is_word_boundary"] = True

        row = self._structures.update_name_form_fields(form_id, update_fields)
        emit_event(
            "structure_name_form.updated",
            "structure",
            existing["structure_id"],
            {"form_id": form_id, "fields": sorted(update_fields)},
        )
        return row

    def delete_name_form(self, form_id: int) -> None:
        """Supprime une forme de nom. Lève `NotFoundError` si elle n'existe pas."""
        row = self._structures.delete_name_form(form_id)
        if not row:
            raise NotFoundError(f"Forme {form_id} introuvable")
        emit_event(
            "structure_name_form.deleted",
            "structure",
            row["structure_id"],
            {"form_id": form_id, "form_text": row["form_text"]},
        )
