"""Command handlers des écritures API sur les revues : frontière transactionnelle de l'agrégat.

`update_serial` et `merge_serials` requalifient dans la foulée le `doc_type` des publications rattachées quand le `serial_type` cible change.
"""

from sqlalchemy import Connection

from application.ports.pipeline.serial_recompute import SerialRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.serial_repository import SerialRepository, SerialUpdate
from application.services.serials import core as serials_service
from domain.serials.serial import SerialType


def update_serial(
    conn: Connection,
    serial_id: int,
    *,
    update: SerialUpdate,
    repo: SerialRepository,
    recompute: SerialRecompute,
    audit_repo: AuditRepository,
) -> None:
    """Met à jour une revue (champs sélectifs). Si `serial_type` ou `oa_model` change effectivement, rejoue les corrections des publications rattachées dans la même transaction : leur `doc_type` suit le type de la revue, leur statut diamant son modèle OA."""
    corrections_changed = serials_service.update_serial(
        serial_id, update=update, repo=repo, audit_repo=audit_repo
    )

    if corrections_changed:
        serials_service.requalify_publications_for_serial(
            serial_id, conn=conn, recompute=recompute, audit_repo=audit_repo
        )
    conn.commit()


def preview_type_change_impact(
    conn: Connection,
    serial_id: int,
    *,
    serial_type: SerialType,
    repo: SerialRepository,
    recompute: SerialRecompute,
) -> int:
    """Compte les publications de la revue dont le `doc_type` changerait si son `serial_type` passait à `serial_type`.

    Applique réellement l'édition (écriture du type puis requalification) dans un `SAVEPOINT` annulé : l'aperçu emprunte le chemin exact de l'édition (`update_serial`), et aucune écriture ne survit. Lève `NotFoundError` sur une revue inconnue, comme l'édition simulée.
    """
    savepoint = conn.begin_nested()
    try:
        serials_service.update_serial(
            serial_id, update=SerialUpdate(serial_type=serial_type), repo=repo
        )
        return serials_service.requalify_publications_for_serial(
            serial_id, conn=conn, recompute=recompute
        )
    finally:
        savepoint.rollback()


def merge_serials(
    conn: Connection,
    target_id: int,
    source_id: int,
    *,
    repo: SerialRepository,
    recompute: SerialRecompute,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne la revue source dans la cible (transferts publications +
    métadonnées, requalification contre le `serial_type` cible, suppression
    de la source)."""
    serials_service.merge_serials(
        target_id,
        source_id,
        conn=conn,
        repo=repo,
        recompute=recompute,
        audit_repo=audit_repo,
    )
    conn.commit()
