"""Service des publications en série — écritures sur l'agrégat Serial.

Le `serial_type` d'une revue alimente des règles de correction du `doc_type` de ses publications. Après une édition ou une fusion, le pipeline rejoue ces corrections (`SerialRecompute`).
"""

from decimal import Decimal

from sqlalchemy import Connection

from application.audit_log import discarded_events, emit_event
from application.ports.pipeline.serial_recompute import SerialRecompute
from application.ports.repositories.serial_repository import SerialRepository, SerialUpdate
from application.services._merge import check_merge_pair
from domain.errors import NotFoundError, ValidationError
from domain.serials.issns import SerialIssn
from domain.serials.serial import ManualField, SerialEdit, SerialType


def update_serial(
    serial_id: int,
    *,
    update: SerialUpdate,
    repo: SerialRepository,
    recompute: SerialRecompute,
) -> int:
    """Charge la revue, applique les champs explicitement fournis (`Serial.edit`), persiste. Si le `serial_type` ou le `oa_model` change effectivement, rejoue les corrections des publications de la revue : leur `doc_type` suit le type de la revue, leur statut diamant son modèle OA. Retourne le nombre de publications dont le `doc_type` change.

    Un `null` sur un champ obligatoire (titre, type, caractère académique) vaut champ non fourni. L'événement d'audit contient seulement les champs soumis.

    Lève `ValidationError` si aucun champ n'est fourni ou si les ISSN sont invalides, `NotFoundError` si la revue n'existe pas.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    serial = repo.find_by_id(serial_id)
    if serial is None:
        raise NotFoundError(f"Revue {serial_id} introuvable")

    changed = serial.edit(**_serial_edit(update))
    repo.save(serial)
    emit_event(
        "serial.updated",
        "serial",
        serial_id,
        update.model_dump(exclude_unset=True, mode="json"),
    )
    if not changed & {ManualField.SERIAL_TYPE, ManualField.OA_MODEL}:
        return 0
    return requalify_publications_for_serial(serial_id, recompute=recompute)


def preview_type_change_impact(
    serial_id: int,
    *,
    serial_type: SerialType,
    conn: Connection,
    repo: SerialRepository,
    recompute: SerialRecompute,
) -> int:
    """Compte les publications de la revue dont le `doc_type` changerait si son `serial_type` passait à `serial_type`.

    Applique réellement l'édition (`update_serial`) dans un `SAVEPOINT` annulé : l'aperçu emprunte le chemin exact de l'édition, et aucune écriture ne survit, ni aucun événement d'audit. Lève `NotFoundError` sur une revue inconnue, comme l'édition simulée.
    """
    savepoint = conn.begin_nested()
    try:
        with discarded_events():
            return update_serial(
                serial_id,
                update=SerialUpdate(serial_type=serial_type),
                repo=repo,
                recompute=recompute,
            )
    finally:
        savepoint.rollback()


def _serial_edit(update: SerialUpdate) -> SerialEdit:
    """Champs fournis de `update`, sous la forme que l'agrégat reçoit."""
    provided = update.model_fields_set
    changes = SerialEdit()
    if "title" in provided and update.title is not None:
        changes["title"] = update.title
    if "issns" in provided:
        changes["issns"] = [SerialIssn(**row.model_dump()) for row in update.issns or []]
    if "serial_type" in provided and update.serial_type is not None:
        changes["serial_type"] = update.serial_type
    if "oa_model" in provided:
        changes["oa_model"] = update.oa_model
    if "is_academic" in provided and update.is_academic is not None:
        changes["is_academic"] = update.is_academic
    if "apc_amount" in provided:
        amount = update.apc_amount
        changes["apc_amount_eur"] = None if amount is None else Decimal(str(amount))
    return changes


def merge_serials(
    target_id: int,
    source_id: int,
    *,
    repo: SerialRepository,
    recompute: SerialRecompute,
) -> None:
    """Fusionne la revue source dans la revue cible, par le pipeline, qui requalifie les publications absorbées.

    Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` sur une revue introuvable.
    """
    check_merge_pair(target_id, source_id, repo.find_by_id, label="Revue")
    recompute.merge_serials(target_id, source_id)
    emit_event("serial.merged", "serial", target_id, {"source_id": source_id})


# ── Requalification des publications d'un journal après changement d'un champ éditable ──


def requalify_publications_for_serial(
    serial_id: int,
    *,
    recompute: SerialRecompute,
) -> int:
    """Requalifie, par le pipeline, le `doc_type` des publications d'une revue après un changement de son `serial_type`.

    Précondition : l'appelant a déjà écrit le `serial_type`, dans la même transaction. Retourne le nombre de publications dont le `doc_type` change, et émet l'audit `serial.type_requalified` si ce nombre est positif.
    """
    changed = recompute.requalify_publications(serial_id)
    if changed > 0:
        emit_event(
            "serial.type_requalified",
            "serial",
            serial_id,
            {"count": changed},
        )
    return changed
