"""Command handlers des écritures API sur les éditeurs : frontière transactionnelle de l'agrégat.

`merge_publishers` transfère revues et publications, fusionne les revues à titre partagé, puis supprime l'éditeur source.
"""

from sqlalchemy import Connection

from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.services.publishers import core as publishers


def update_publisher(
    conn: Connection,
    publisher_id: int,
    *,
    update: PublisherUpdate,
    repo: PublisherRepository,
) -> None:
    """Met à jour un éditeur (champs sélectifs)."""
    publishers.update_publisher(publisher_id, update=update, repo=repo)
    conn.commit()


def merge_publishers(
    conn: Connection,
    target_id: int,
    source_id: int,
    *,
    correction_queries: MetadataCorrectionQueries,
    publisher_repo: PublisherRepository,
    journal_repo: JournalRepository,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne l'éditeur source dans l'éditeur cible (transferts revues +
    publications, fusion des revues à titre partagé, suppression de la source)."""
    publishers.merge_publishers(
        target_id,
        source_id,
        conn=conn,
        correction_queries=correction_queries,
        publisher_repo=publisher_repo,
        journal_repo=journal_repo,
        pub_repo=pub_repo,
        audit_repo=audit_repo,
    )
    conn.commit()
