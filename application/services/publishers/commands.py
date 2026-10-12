"""Command handlers des écritures API sur les éditeurs : frontière transactionnelle de l'agrégat.

`merge_publishers` transfère revues et publications, fusionne les revues à titre partagé, puis supprime l'éditeur source.
"""

from sqlalchemy import Connection

from application.ports.pipeline.journal_recompute import JournalRecompute
from application.ports.pipeline.pub_count import PubCountRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.services.publishers import core as publishers_service


def update_publisher(
    conn: Connection,
    publisher_id: int,
    *,
    update: PublisherUpdate,
    repo: PublisherRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Met à jour un éditeur (champs sélectifs)."""
    publishers_service.update_publisher(
        publisher_id, update=update, repo=repo, audit_repo=audit_repo
    )
    conn.commit()


def merge_publishers(
    conn: Connection,
    target_id: int,
    source_id: int,
    *,
    publisher_repo: PublisherRepository,
    journal_repo: JournalRepository,
    recompute: JournalRecompute,
    pub_count_recompute: PubCountRecompute,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne l'éditeur source dans l'éditeur cible (transferts revues +
    publications, fusion des revues à titre partagé, suppression de la source)."""
    publishers_service.merge_publishers(
        target_id,
        source_id,
        conn=conn,
        publisher_repo=publisher_repo,
        journal_repo=journal_repo,
        recompute=recompute,
        pub_count_recompute=pub_count_recompute,
        audit_repo=audit_repo,
    )
    conn.commit()
