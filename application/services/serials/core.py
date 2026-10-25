"""Service des publications en série — écritures sur l'agrégat Serial, transaction-agnostiques.

Les opérations sur l'agrégat Publisher vivent dans `application/services/publishers/core.py` ; les deux agrégats restent liés par `serials.publisher_id` (FK), chacun manipulé par son propre service et son propre port.

Le `serial_type` d'une revue alimente des règles de correction du `doc_type` de ses publications. Après une édition ou une fusion, le pipeline rejoue ces corrections (`SerialRecompute`).
"""

from decimal import Decimal

from sqlalchemy import Connection

from application.audit_log import emit_event
from application.ports.pipeline.serial_recompute import SerialRecompute
from application.ports.repositories.audit_repository import AuditRepository
from application.ports.repositories.serial_repository import SerialRepository, SerialUpdate
from application.services._merge import load_merge_pair
from domain.errors import NotFoundError, ValidationError
from domain.serials.issns import (
    SerialIssn,
    validate_serial_issns,
)
from domain.serials.serial import ManualField


def update_serial(
    serial_id: int,
    *,
    update: SerialUpdate,
    repo: SerialRepository,
    audit_repo: AuditRepository | None = None,
) -> bool:
    """Charge la revue, applique les champs explicitement fournis, persiste. Retourne `True` si le `serial_type` ou le `oa_model` a effectivement changé : le command handler rejoue alors les corrections des publications de la revue.

    L'événement d'audit contient seulement les champs soumis.

    Les ISSN fournis deviennent les ISSN de la revue ; `validate_serial_issns` les normalise. Un titre, des ISSN, un type, un modèle OA ou un APC modifiés deviennent des champs saisis à la main (`ManualField`), que le pipeline laisse en l'état. L'APC saisi est en euros.

    Lève `ValidationError` si aucun champ n'est fourni ou si les ISSN sont invalides, `NotFoundError` si la revue n'existe pas.
    """
    if not update.model_fields_set:
        raise ValidationError("Aucun champ à mettre à jour")

    serial = repo.find_by_id(serial_id)
    if serial is None:
        raise NotFoundError(f"Revue {serial_id} introuvable")

    old_title = serial.title
    old_issns = list(serial.issns)
    old_type = serial.serial_type
    old_oa_model = serial.oa_model
    old_apc_amount = serial.apc_amount
    champs = update.model_dump(exclude_unset=True, mode="json")
    # Les champs de `SerialUpdate` ont les noms des attributs de l'agrégat.
    for field_name in update.model_fields_set:
        if field_name == "issns":
            serial.issns = validate_serial_issns(
                SerialIssn(**row.model_dump()) for row in update.issns or []
            )
        elif field_name == "apc_amount":
            # Montant au centime, comme la colonne : la comparaison à l'ancien montant reste exacte.
            serial.apc_amount = (
                Decimal(str(update.apc_amount)).quantize(Decimal("0.01"))
                if update.apc_amount is not None
                else None
            )
        else:
            setattr(serial, field_name, getattr(update, field_name))
    if serial.title != old_title:
        serial.manual_fields |= {ManualField.TITLE}
    if serial.issns != old_issns:
        serial.manual_fields |= {ManualField.ISSNS}
    if serial.serial_type != old_type:
        serial.manual_fields |= {ManualField.SERIAL_TYPE}
    if serial.oa_model != old_oa_model:
        serial.manual_fields |= {ManualField.OA_MODEL}
    if serial.apc_amount != old_apc_amount:
        # Le formulaire saisit l'APC en euros.
        serial.apc_currency = "EUR" if serial.apc_amount is not None else None
        serial.manual_fields |= {ManualField.APC}
    repo.save(serial)
    emit_event(audit_repo, "serial.updated", "serial", serial_id, champs)
    return serial.serial_type != old_type or serial.oa_model != old_oa_model


def merge_serials(
    target_id: int,
    source_id: int,
    *,
    conn: Connection,
    repo: SerialRepository,
    recompute: SerialRecompute,
    audit_repo: AuditRepository | None = None,
) -> None:
    """Fusionne la revue source dans la revue cible, par le pipeline, qui requalifie les publications absorbées.

    Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` sur une revue introuvable.
    """
    load_merge_pair(target_id, source_id, repo.find_by_id, label="Revue")
    recompute.merge_serials(conn, target_id, source_id)
    emit_event(audit_repo, "serial.merged", "serial", target_id, {"source_id": source_id})


# ── Requalification des publications d'un journal après changement d'un champ éditable ──


def requalify_publications_for_serial(
    serial_id: int,
    *,
    conn: Connection,
    recompute: SerialRecompute,
    audit_repo: AuditRepository | None = None,
) -> int:
    """Requalifie, par le pipeline, le `doc_type` des publications d'une revue après un changement de son `serial_type`.

    Précondition : l'appelant a déjà écrit le `serial_type`, dans la même transaction. Retourne le nombre de publications dont le `doc_type` change, et émet l'audit `serial.type_requalified` si ce nombre est positif.

    Un appel dans un `SAVEPOINT` que l'appelant annule donne l'aperçu de la requalification.
    """
    changed = recompute.requalify_publications(conn, serial_id)
    if changed > 0:
        emit_event(
            audit_repo,
            "serial.type_requalified",
            "serial",
            serial_id,
            {"count": changed},
        )
    return changed
