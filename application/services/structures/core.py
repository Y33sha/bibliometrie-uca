"""
Service Structures — orchestrateur des opérations sur `structures`, `structure_relations`, `structure_name_forms`.

Le SQL vit dans `infrastructure/repositories/structure_repository.py`. La validation du JSONB `api_ids` se fait à la frontière infra (repo) plutôt qu'ici — tout chemin d'écriture (service applicatif + scripts CLI éventuels) passe par le repo, donc la validation y est appliquée uniformément.

Les routers passent par ces fonctions pour toute écriture. Les lectures restent autorisées dans les routers (convention du projet).
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
    StructureUpdateFields,
)
from domain.errors import NotFoundError, ValidationError
from domain.normalize import normalize_text
from domain.structures.identifiers import RorId
from domain.structures.name_forms import is_short_form
from domain.structures.relations import check_can_create_relation
from domain.types import JsonValue

# ── Mapping des champs UI → colonnes SQL pour la table structures ──
_STRUCTURE_FIELD_MAP = {
    "name": "name",
    "acronym": "acronym",
    "type": "structure_type",
    "ror_id": "ror_id",
    "rnsr_id": "rnsr_id",
    "hal_collection": "hal_collection",
}


def _normalize_ror_id(raw: str | None) -> str | None:
    """Forme canonique courte du ror_id (le VO `RorId` strip l'URL `https://ror.org/`),
    ou `None` si vide. Lève `ValidationError` si une valeur non vide n'est pas un ROR valide.

    Seule barrière d'écriture : tout chemin (form admin, import, futur appelant) passe par
    le service, donc une URL complète envoyée par un client est ramenée à l'ID 9-char ici.
    """
    if not raw or not raw.strip():
        return None
    parsed = RorId.try_parse(raw)
    if parsed is None:
        raise ValidationError(f"ror_id invalide : {raw!r}")
    return parsed.value


# ── structures ────────────────────────────────────────────────────


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
    """Crée une structure. Retourne la ligne insérée."""
    row = repo.create_structure(
        code=code,
        name=name,
        acronym=acronym,
        type=type,
        ror_id=_normalize_ror_id(ror_id),
        rnsr_id=rnsr_id,
        hal_collection=hal_collection,
        api_ids=api_ids,
    )
    emit_event(
        audit_repo,
        "structure.created",
        "structure",
        row["id"],
        {"code": code, "name": name, "type": type},
    )
    return row


def update_structure(
    structure_id: int, *, fields: dict[str, JsonValue], repo: StructureRepository
) -> StructureRow:
    """Met à jour une structure. Retourne la ligne modifiée.

    Lève NotFoundError si la structure n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    if not repo.structure_exists(structure_id):
        raise NotFoundError(f"Structure {structure_id} introuvable")

    update_fields: StructureUpdateFields = {}
    for field_name, col_name in _STRUCTURE_FIELD_MAP.items():
        val = fields.get(field_name)
        if val is not None:
            update_fields[col_name] = val  # type: ignore[literal-required]

    if "ror_id" in update_fields:
        update_fields["ror_id"] = _normalize_ror_id(update_fields["ror_id"])

    api_ids = fields.get("api_ids")
    if isinstance(api_ids, dict):
        # SA sérialise auto en JSONB depuis un dict Python ; pas de Json() wrap.
        # Validation appliquée côté repo.
        update_fields["api_ids"] = cast("dict[str, str | list[str]]", api_ids)

    if not update_fields:
        raise ValidationError("Aucun champ à mettre à jour")

    return repo.update_structure_fields(structure_id, update_fields)


def delete_structure(
    structure_id: int,
    *,
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Supprime une structure. Lève NotFoundError si elle n'existe pas.

    Cascade DB via FK `ON DELETE CASCADE` sur `authorship_structures` et `source_authorship_structures`. Le nettoyage du périmètre (retrait des racines de `perimeters.structure_ids`, rematérialisation de la clôture) relève du command handler.
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
) -> StructureRelationRow | None:
    """Crée une relation. Retourne la ligne insérée, ou None si elle existait déjà.

    Lève `ValidationError` si la relation viole l'invariant de graphe
    (auto-référence `parent_id == child_id` ou cycle : `child_id` est déjà
    un ancêtre de `parent_id`). Les ancêtres sont prefetched via
    `repo.get_ancestor_ids` et la validation est déléguée au domain.
    """
    check_can_create_relation(
        parent_id=parent_id,
        child_id=child_id,
        ancestors_of_parent=repo.get_ancestor_ids(parent_id),
    )
    return repo.create_relation(
        parent_id=parent_id,
        child_id=child_id,
        relation_type=relation_type,
    )


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
) -> StructureNameFormRow:
    """Crée une forme de nom. Retourne la ligne insérée."""
    form_text_normalized = normalize_text(form_text)
    return repo.create_name_form(
        structure_id=structure_id,
        form_text_normalized=form_text_normalized,
        # Forme courte ⇒ frontière de mot forcée (invariant verrouillé par une CHECK).
        is_word_boundary=is_word_boundary or is_short_form(form_text_normalized),
        is_excluding=is_excluding,
        requires_context_of=requires_context_of,
    )


def update_name_form(
    form_id: int, *, fields: dict[str, JsonValue], repo: StructureRepository
) -> StructureNameFormRow:
    """Met à jour une forme de nom. Retourne la ligne modifiée.

    Lève NotFoundError si la forme n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    if not repo.name_form_exists(form_id):
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

    # Forme courte ⇒ frontière de mot forcée (invariant verrouillé par une CHECK).
    new_form_text = update_fields.get("form_text")
    if isinstance(new_form_text, str) and is_short_form(new_form_text):
        update_fields["is_word_boundary"] = True

    if not update_fields:
        raise ValidationError("Aucun champ à mettre à jour")

    return repo.update_name_form_fields(form_id, update_fields)


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
