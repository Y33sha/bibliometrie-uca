"""Command handlers des écritures API sur les monographies : frontière transactionnelle de l'agrégat."""

from sqlalchemy import Connection

from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.monograph_repository import MonographRepository, MonographUpdate
from application.services.monographs import editing


def update_monograph(
    conn: Connection,
    monograph_id: int,
    *,
    update: MonographUpdate,
    repo: MonographRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Met à jour une monographie (champs sélectifs)."""
    editing.update_monograph(monograph_id, update=update, repo=repo, audit_repo=audit_repo)
    conn.commit()
