"""
Service Structures — orchestrateur des opérations sur `structures`,
`structure_relations`, `structure_name_forms`.

Le SQL vit dans `infrastructure/repositories/structure_repository.py`.
La validation du JSONB `api_ids` se fait à la frontière infra (repo)
plutôt qu'ici — tout chemin d'écriture (service applicatif + scripts
CLI éventuels) passe par le repo, donc la validation y est appliquée
uniformément.

Les routers passent par ces fonctions pour toute écriture. Les lectures
restent autorisées dans les routers (convention du projet).
"""

from application.audit import emit_event
from domain.errors import NotFoundError, ValidationError
from domain.normalize import normalize_text
from domain.ports.audit_repository import AuditRepository
from domain.ports.structure_repository import StructureRepository

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


def create_structure(
    *,
    code: str,
    name: str,
    acronym: str | None = None,
    type: str,
    ror_id: str | None = None,
    rnsr_id: str | None = None,
    hal_collection: str | None = None,
    api_ids: dict | None = None,
    repo: StructureRepository,
) -> dict:
    """Crée une structure. Retourne la ligne insérée (dict)."""
    return repo.create_structure(
        code=code,
        name=name,
        acronym=acronym,
        type=type,
        ror_id=ror_id,
        rnsr_id=rnsr_id,
        hal_collection=hal_collection,
        api_ids=api_ids,
    )


def update_structure(structure_id: int, *, fields: dict, repo: StructureRepository) -> dict:
    """Met à jour une structure. Retourne la ligne modifiée.

    Lève NotFoundError si la structure n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    if not repo.structure_exists(structure_id):
        raise NotFoundError(f"Structure {structure_id} introuvable")

    update_fields: dict = {}
    for field_name, col_name in _STRUCTURE_FIELD_MAP.items():
        val = fields.get(field_name)
        if val is not None:
            update_fields[col_name] = val

    if "api_ids" in fields and fields["api_ids"] is not None:
        # SA sérialise auto en JSONB depuis un dict Python ; pas de Json() wrap.
        # Validation appliquée côté repo.
        update_fields["api_ids"] = fields["api_ids"]

    if not update_fields:
        raise ValidationError("Aucun champ à mettre à jour")

    return repo.update_structure_fields(structure_id, update_fields)


def delete_structure(
    structure_id: int,
    *,
    repo: StructureRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Supprime une structure. Lève NotFoundError si elle n'existe pas."""
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
) -> dict | None:
    """Crée une relation. Retourne la ligne insérée, ou None si elle existait déjà."""
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
    requires_context_of: list | None = None,
    repo: StructureRepository,
) -> dict:
    """Crée une forme de nom. Retourne la ligne insérée."""
    return repo.create_name_form(
        structure_id=structure_id,
        form_text_normalized=normalize_text(form_text),
        is_word_boundary=is_word_boundary,
        is_excluding=is_excluding,
        requires_context_of=requires_context_of,
    )


def update_name_form(form_id: int, *, fields: dict, repo: StructureRepository) -> dict:
    """Met à jour une forme de nom. Retourne la ligne modifiée.

    Lève NotFoundError si la forme n'existe pas.
    Lève ValidationError si `fields` ne contient aucun champ valide.
    """
    if not repo.name_form_exists(form_id):
        raise NotFoundError(f"Forme {form_id} introuvable")

    update_fields: dict = {}

    if fields.get("form_text") is not None:
        update_fields["form_text"] = normalize_text(fields["form_text"])
    if fields.get("is_word_boundary") is not None:
        update_fields["is_word_boundary"] = fields["is_word_boundary"]
    if fields.get("is_excluding") is not None:
        update_fields["is_excluding"] = fields["is_excluding"]
    if fields.get("requires_context_of") is not None:
        update_fields["requires_context_of"] = fields["requires_context_of"] or None

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
