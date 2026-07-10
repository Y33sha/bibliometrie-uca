"""Command handlers des écritures API sur les publications : la frontière transactionnelle.

Une écriture API est une commande (intention courte d'un acteur). Chaque handler
reçoit la connexion de la requête, compose les briques agnostiques de `core.py`
et `conn.commit()` au succès — pour que la donnée soit persistée avant l'envoi de
la réponse (cf. `docs/chantiers/CODE_commit-avant-reponse.md`). Les briques
composées restent transaction-agnostiques (réutilisées par le pipeline et les
CLI) ; seul le command handler commit.
"""

from sqlalchemy import Connection

from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publication_repository import PublicationRepository
from application.services.publications import core as publications_service


def merge_publications(
    conn: Connection,
    target_id: int,
    source_id: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository,
) -> None:
    """Fusionne deux publications doublons puis re-dérive les métadonnées
    canoniques de la cible depuis l'union des sources, en une seule transaction.

    La cible (survivante) est l'id le plus petit : côté publications le sens de
    fusion n'a pas d'effet durable, `refresh_from_sources` re-dérivant tout depuis
    l'union des `source_publications`.
    """
    publications_service.merge_publications(target_id, source_id, repo=repo, audit_repo=audit_repo)
    publications_service.refresh_from_sources(target_id, repo=repo, audit_repo=audit_repo)
    conn.commit()


def mark_distinct(
    conn: Connection,
    pub_id_a: int,
    pub_id_b: int,
    *,
    repo: PublicationRepository,
    audit_repo: AuditRepository,
) -> None:
    """Marque deux publications comme distinctes (non-doublon confirmé)."""
    publications_service.mark_distinct(pub_id_a, pub_id_b, repo=repo, audit_repo=audit_repo)
    conn.commit()
