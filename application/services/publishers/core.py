"""Service Éditeurs — écritures sur l'agrégat Publisher.

Agrégat distinct de Serial, servi par son propre port (`PublisherRepository`). Un appelant qui ne touche qu'aux éditeurs (ex. `update_publisher` d'un router admin) charge cette seule surface.

La fusion d'éditeurs (`merge_publishers`) vit ici : c'est une opération de l'agrégat Publisher. Elle prend aussi le port `SerialRepository` pour détecter les journaux en conflit entre les deux éditeurs avant de déléguer les transferts SQL.
"""

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.publication_count import PublicationCountRecompute
from application.ports.pipeline.serial_recompute import SerialRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.ports.repositories.serial_repository import SerialRepository
from application.services._merge import load_merge_pair
from application.services.serials.core import merge_serials
from domain.errors import (
    ConflictError,
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from domain.publishers.members import crossref_member_conflict
from domain.publishers.merge import split_shared_title_pairs


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
    serial_repo: SerialRepository,
    recompute: SerialRecompute,
    publication_count_recompute: PublicationCountRecompute,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne l'éditeur source dans l'éditeur cible, puis le pipeline recalcule le `publication_count` de la cible.

    Deux invariants métier refusent la fusion (`ConflictError`), chacun sur un identifiant déclaré : des membres Crossref distincts de part et d'autre, ou deux journaux au titre partagé dont les ISSN diffèrent.

    La détection est côté `serial_repo` (requête sur `serials`), la fusion finale côté `publisher_repo` (transferts + delete).

    Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` sur un éditeur introuvable.
    """
    load_merge_pair(target_id, source_id, publisher_repo.find_by_id, label="Éditeur")

    # 1. Deux membres Crossref distincts désignent deux éditeurs : la fusion s'arrête là.
    if conflict := crossref_member_conflict(
        publisher_repo.crossref_member_ids(target_id),
        publisher_repo.crossref_member_ids(source_id),
    ):
        raise ConflictError(f"Fusion refusée, {conflict} (cible / source)")

    # 2. Les revues homonymes des deux éditeurs fusionnent, sauf si une paire bloque. Toutes les
    #    paires bloquantes partent ensemble dans l'erreur : l'UI les affiche d'un coup.
    mergeable_pairs, blockers = split_shared_title_pairs(
        serial_repo.find_shared_title_serial_pairs(target_id, source_id)
    )
    if blockers:
        raise PublisherMergeBlockedError(blockers)

    for pair in mergeable_pairs:
        merge_serials(
            pair.target_serial_id,
            pair.source_serial_id,
            conn=conn,
            repo=serial_repo,
            recompute=recompute,
            audit_repo=audit_repo,
        )

    # 3. Les données de l'éditeur absorbé, selon leur règle de fusion.
    publisher_repo.merge_publisher_into(target_id, source_id)
    publication_count_recompute.refresh_publisher_publication_count(conn, target_id)

    emit_event(audit_repo, "publisher.merged", "publisher", target_id, {"source_id": source_id})
