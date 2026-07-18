"""Command handlers des écritures API sur les périmètres : frontière transactionnelle de l'agrégat.

`update_perimeter` et `add_structure_to_perimeter` rafraîchissent en plus la clôture matérialisée, dont les racines du périmètre commandent la descente.
"""

from sqlalchemy import Connection

from application.ports.config import ConfigStore
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdate,
)
from application.services.perimeters import core as perimeters_service
from application.services.perimeters.core import AddStructureOutcome


def create_perimeter(
    conn: Connection,
    *,
    code: str,
    name: str,
    repo: PerimeterRepository,
) -> int:
    """Crée un périmètre. Retourne l'id créé."""
    pid = perimeters_service.create_perimeter(code=code, name=name, repo=repo)
    conn.commit()
    return pid


def update_perimeter(
    conn: Connection,
    perimeter_id: int,
    *,
    update: PerimeterUpdate,
    repo: PerimeterRepository,
) -> None:
    """Met à jour un périmètre à partir des champs explicitement fournis."""
    perimeters_service.update_perimeter(perimeter_id, update=update, repo=repo)
    repo.refresh_structures()
    conn.commit()


def delete_perimeter(
    conn: Connection,
    perimeter_id: int,
    *,
    repo: PerimeterRepository,
    config: ConfigStore,
    audit_repo: AuditRepository,
) -> None:
    """Supprime un périmètre (interdit s'il est référencé par la config pipeline)."""
    perimeters_service.delete_perimeter(
        perimeter_id, repo=repo, config=config, audit_repo=audit_repo
    )
    conn.commit()


def add_structure_to_perimeter(
    conn: Connection,
    perimeter_id: int,
    structure_id: int,
    *,
    repo: PerimeterRepository,
) -> AddStructureOutcome:
    """Ajoute une structure racine au périmètre. Retourne l'issue."""
    outcome = perimeters_service.add_structure_to_perimeter(perimeter_id, structure_id, repo=repo)
    repo.refresh_structures()
    conn.commit()
    return outcome
