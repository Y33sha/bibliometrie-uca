"""Service Éditeurs — écritures sur l'agrégat Publisher, transaction-agnostiques.

Agrégat distinct de Journal, servi par son propre port (`PublisherRepository`). Un appelant qui ne touche qu'aux éditeurs (ex. `update_publisher` d'un router admin) charge cette seule surface.

La fusion d'éditeurs (`merge_publishers`) vit ici : c'est une opération de l'agrégat Publisher. Elle prend aussi le port `JournalRepository` pour détecter les journaux en conflit entre les deux éditeurs avant de déléguer les transferts SQL.
"""

from collections import Counter

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.journal_recompute import JournalRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.journal_repository import JournalRepository
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.services._merge import load_merge_pair
from application.services.journals.core import merge_journals
from domain.errors import (
    BlockingJournal,
    ConflictError,
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from domain.journals.issns import issn_conflict
from domain.publishers.members import crossref_member_conflict


def update_publisher(
    publisher_id: int,
    *,
    update: PublisherUpdate,
    repo: PublisherRepository,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Charge l'éditeur, applique les champs explicitement fournis, persiste.

    L'événement d'audit contient seulement les champs soumis.

    Lève `ValidationError` si aucun champ n'est fourni, `NotFoundError` si l'éditeur n'existe pas.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    publisher = repo.find_by_id(publisher_id)
    if publisher is None:
        raise NotFoundError(f"Éditeur {publisher_id} introuvable")

    # Les champs de `PublisherUpdate` ont les noms des attributs de l'agrégat.
    champs = update.model_dump(exclude_unset=True, mode="json")
    for field_name, value in update.model_dump(exclude_unset=True).items():
        setattr(publisher, field_name, value)
    repo.save(publisher)
    emit_event(audit_repo, "publisher.updated", "publisher", publisher_id, champs)


def merge_publishers(
    target_id: int,
    source_id: int,
    *,
    conn: Connection,
    publisher_repo: PublisherRepository,
    journal_repo: JournalRepository,
    recompute: JournalRecompute,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne l'éditeur source dans l'éditeur cible.

    Deux invariants métier refusent la fusion (`ConflictError`), chacun sur une identité déclarée : des membres Crossref distincts de part et d'autre, ou deux journaux au titre partagé dont les ISSN diffèrent.

    La détection est côté `journal_repo` (requête sur `journals`), la fusion finale côté `publisher_repo` (transferts + delete).

    Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` sur un éditeur introuvable.
    """
    load_merge_pair(target_id, source_id, publisher_repo.find_by_id, label="Éditeur")

    # 1. Deux identités Crossref distinctes désignent deux éditeurs : la fusion s'arrête là.
    if conflict := crossref_member_conflict(
        publisher_repo.crossref_member_ids(target_id),
        publisher_repo.crossref_member_ids(source_id),
    ):
        raise ConflictError(f"Fusion refusée, {conflict} (cible / source)")

    # 2. Détecter les journaux partageant un titre entre les deux éditeurs.
    #    Collecter toutes les paires bloquantes en une passe pour lever
    #    PublisherMergeBlockedError avec l'ensemble — l'UI les affiche
    #    d'un coup.
    pairs = journal_repo.find_shared_title_journal_pairs(target_id, source_id)
    # Si un journal apparaît dans plusieurs paires, l'éditeur correspondant
    # contient un doublon interne (2 journaux au même title_normalized). La
    # fusion N→1 casserait (la source supprimée puis rechargée). On signale
    # toutes les paires concernées comme bloquantes.
    target_seen = Counter(p["target_journal_id"] for p in pairs)
    source_seen = Counter(p["source_journal_id"] for p in pairs)
    blockers: list[BlockingJournal] = []
    mergeable_pairs = []
    for pair in pairs:
        reasons: list[str] = []
        if target_seen[pair["target_journal_id"]] > 1:
            reasons.append("doublon interne dans l'éditeur cible (titre dédupliqué)")
        if source_seen[pair["source_journal_id"]] > 1:
            reasons.append("doublon interne dans l'éditeur source (titre dédupliqué)")
        if conflict := issn_conflict(pair["t_issns"], pair["s_issns"]):
            reasons.append(f"{conflict} (cible / source)")
        if reasons:
            blockers.append(
                BlockingJournal(
                    target_journal_id=pair["target_journal_id"],
                    target_title=pair["t_title"],
                    source_journal_id=pair["source_journal_id"],
                    source_title=pair["s_title"],
                    reason=" ; ".join(reasons),
                )
            )
        else:
            mergeable_pairs.append(pair)
    if blockers:
        raise PublisherMergeBlockedError(blockers)

    for pair in mergeable_pairs:
        merge_journals(
            pair["target_journal_id"],
            pair["source_journal_id"],
            conn=conn,
            repo=journal_repo,
            recompute=recompute,
            audit_repo=audit_repo,
        )

    # 3. Les données de l'éditeur absorbé, selon leur règle de fusion.
    publisher_repo.merge_publisher_into(target_id, source_id)

    emit_event(audit_repo, "publisher.merged", "publisher", target_id, {"source_id": source_id})
