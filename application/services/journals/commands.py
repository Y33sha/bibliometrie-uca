"""Command handlers des écritures API sur les revues : frontière transactionnelle de l'agrégat.

`update_journal` et `merge_journals` requalifient dans la foulée le `doc_type` des publications rattachées quand le `journal_type` cible change.
"""

from sqlalchemy import Connection

from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository, JournalUpdate
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.journals import core as journals_service


def update_journal(
    conn: Connection,
    journal_id: int,
    *,
    update: JournalUpdate,
    repo: JournalRepository,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository,
    correction_queries: MetadataCorrectionQueries,
) -> None:
    """Met à jour une revue (champs sélectifs). Si `journal_type` change
    effectivement, requalifie le `doc_type` des publications rattachées dans la
    même transaction."""
    new_type = update.journal_type
    type_changed = False
    if isinstance(new_type, str):
        existing = repo.find_by_id(journal_id)
        if existing is not None and existing.journal_type != new_type:
            type_changed = True

    journals_service.update_journal(journal_id, update=update, repo=repo)

    if type_changed:
        journals_service.requalify_publications_for_journal(
            journal_id,
            conn=conn,
            correction_queries=correction_queries,
            pub_repo=pub_repo,
            audit_repo=audit_repo,
        )
    conn.commit()


def merge_journals(
    conn: Connection,
    target_id: int,
    source_id: int,
    *,
    correction_queries: MetadataCorrectionQueries,
    repo: JournalRepository,
    pub_repo: PublicationRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne la revue source dans la cible (transferts publications +
    métadonnées, requalification contre le `journal_type` cible, suppression
    de la source)."""
    journals_service.merge_journals(
        target_id,
        source_id,
        conn=conn,
        correction_queries=correction_queries,
        repo=repo,
        pub_repo=pub_repo,
        audit_repo=audit_repo,
    )
    conn.commit()
