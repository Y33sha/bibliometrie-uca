"""Command handlers des écritures API sur les revues : la frontière transactionnelle.

Une écriture API est une commande (intention courte d'un acteur). Chaque handler
reçoit la connexion de la requête, compose les briques agnostiques de
`core.py` et `conn.commit()` au succès — pour que la donnée soit persistée
avant l'envoi de la réponse (cf. `docs/chantiers/CODE_commit-avant-reponse.md`).
Les briques composées restent transaction-agnostiques (réutilisées par le
pipeline et les CLI) ; seul le command handler commit.
"""

from sqlalchemy import Connection

from application.ports.pipeline.metadata_correction import MetadataCorrectionQueries
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository, JournalUpdate
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.journals import core as journals


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

    journals.update_journal(journal_id, update=update, repo=repo)

    if type_changed:
        journals.requalify_publications_for_journal(
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
    journals.merge_journals(
        target_id,
        source_id,
        conn=conn,
        correction_queries=correction_queries,
        repo=repo,
        pub_repo=pub_repo,
        audit_repo=audit_repo,
    )
    conn.commit()
