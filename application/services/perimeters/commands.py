"""Command handlers des écritures API sur les périmètres : frontière transactionnelle de l'agrégat.

`create_perimeter` et `update_perimeter` rafraîchissent en plus la clôture matérialisée, dont les racines du périmètre commandent la descente.
"""

from sqlalchemy import Connection

from application.ports.api.config_queries import ConfigQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.perimeter_repository import (
    PerimeterRepository,
    PerimeterUpdate,
)
from application.services.perimeters import core as perimeters_service


def create_perimeter(
    conn: Connection,
    *,
    code: str,
    name: str,
    root_structure_ids: list[int],
    repo: PerimeterRepository,
) -> int:
    """Crée un périmètre avec ses structures racines. Retourne l'id créé."""
    pid = perimeters_service.create_perimeter(
        code=code, name=name, root_structure_ids=root_structure_ids, repo=repo
    )
    repo.refresh_structures()
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
    config: ConfigQueries,
    audit_repo: AuditRepository,
) -> None:
    """Supprime un périmètre (interdit s'il est référencé par la config pipeline)."""
    perimeters_service.delete_perimeter(
        perimeter_id, repo=repo, config=config, audit_repo=audit_repo
    )
    conn.commit()
