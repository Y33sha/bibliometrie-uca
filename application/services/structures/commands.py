"""Command handlers des écritures API sur les structures : frontière transactionnelle de l'agrégat.

Couvre `structures`, `structure_relations`, `structure_name_forms`. `delete_structure`, `create_relation` et `delete_relation` rafraîchissent en plus la clôture matérialisée des périmètres, qu'une tutelle modifiée fait bouger.
"""

from sqlalchemy import Connection

from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import PerimeterRepository
from application.ports.repositories.structure_repository import (
    StructureNameFormRow,
    StructureRelationRow,
    StructureRepository,
    StructureRow,
)
from application.services.structures import core as structures_service
from domain.types import JsonValue

# ── structures ────────────────────────────────────────────────────


def create_structure(
    conn: Connection,
    *,
    code: str,
    name: str,
    acronym: str | None,
    type: str,
    ror_id: str | None,
    rnsr_id: str | None,
    hal_collection: str | None,
    api_ids: dict[str, str | list[str]] | None,
    repo: StructureRepository,
    audit_repo: AuditRepository,
) -> StructureRow:
    """Crée une structure. Retourne la ligne insérée."""
    row = structures_service.create_structure(
        code=code,
        name=name,
        acronym=acronym,
        type=type,
        ror_id=ror_id,
        rnsr_id=rnsr_id,
        hal_collection=hal_collection,
        api_ids=api_ids,
        repo=repo,
        audit_repo=audit_repo,
    )
    conn.commit()
    return row


def update_structure(
    conn: Connection,
    structure_id: int,
    *,
    fields: dict[str, JsonValue],
    repo: StructureRepository,
) -> StructureRow:
    """Met à jour une structure (champs sélectifs). Retourne la ligne modifiée."""
    row = structures_service.update_structure(structure_id, fields=fields, repo=repo)
    conn.commit()
    return row


def delete_structure(
    conn: Connection,
    structure_id: int,
    *,
    repo: StructureRepository,
    perimeter_repo: PerimeterRepository,
    audit_repo: AuditRepository,
) -> None:
    """Supprime une structure (cascade relations + formes de noms), la retire des racines de
    tout périmètre, puis rafraîchit la clôture matérialisée : la structure supprimée et la
    cascade sur ses tutelles en modifient la descente."""
    structures_service.delete_structure(structure_id, repo=repo, audit_repo=audit_repo)
    perimeter_repo.remove_structure_from_all_perimeters(structure_id)
    perimeter_repo.refresh_structures()
    conn.commit()


# ── structure_relations ───────────────────────────────────────────


def create_relation(
    conn: Connection,
    *,
    parent_id: int,
    child_id: int,
    relation_type: str,
    repo: StructureRepository,
    perimeter_repo: PerimeterRepository,
) -> StructureRelationRow | None:
    """Crée une relation parent-enfant. Retourne la ligne insérée, ou None si
    elle existait déjà. Rafraîchit la clôture matérialisée des périmètres : une
    relation `est_tutelle_de` en modifie la descente récursive."""
    row = structures_service.create_relation(
        parent_id=parent_id,
        child_id=child_id,
        relation_type=relation_type,
        repo=repo,
    )
    perimeter_repo.refresh_structures()
    conn.commit()
    return row


def delete_relation(
    conn: Connection,
    relation_id: int,
    *,
    repo: StructureRepository,
    perimeter_repo: PerimeterRepository,
    audit_repo: AuditRepository,
) -> None:
    """Supprime une relation structure. Rafraîchit la clôture matérialisée des
    périmètres (la descente `est_tutelle_de` peut changer)."""
    structures_service.delete_relation(relation_id, repo=repo, audit_repo=audit_repo)
    perimeter_repo.refresh_structures()
    conn.commit()


# ── structure_name_forms ──────────────────────────────────────────


def create_name_form(
    conn: Connection,
    *,
    structure_id: int,
    form_text: str,
    is_word_boundary: bool,
    is_excluding: bool,
    requires_context_of: list[int] | None,
    repo: StructureRepository,
) -> StructureNameFormRow:
    """Crée une forme de nom. Retourne la ligne insérée."""
    row = structures_service.create_name_form(
        structure_id=structure_id,
        form_text=form_text,
        is_word_boundary=is_word_boundary,
        is_excluding=is_excluding,
        requires_context_of=requires_context_of,
        repo=repo,
    )
    conn.commit()
    return row


def update_name_form(
    conn: Connection,
    form_id: int,
    *,
    fields: dict[str, JsonValue],
    repo: StructureRepository,
) -> StructureNameFormRow:
    """Met à jour une forme de nom (champs sélectifs). Retourne la ligne modifiée."""
    row = structures_service.update_name_form(form_id, fields=fields, repo=repo)
    conn.commit()
    return row


def delete_name_form(
    conn: Connection,
    form_id: int,
    *,
    repo: StructureRepository,
    audit_repo: AuditRepository,
) -> None:
    """Supprime une forme de nom."""
    structures_service.delete_name_form(form_id, repo=repo, audit_repo=audit_repo)
    conn.commit()
