"""Service des publications en série : écritures sur l'agrégat Serial.

Le `serial_type` d'une revue alimente des règles de correction du `doc_type` de ses publications. Après une édition ou une fusion, le pipeline rejoue ces corrections (`SerialRecompute`).
"""

from sqlalchemy import Connection

from application.audit_log import discarded_events, emit_event
from application.ports.pipeline.serial_recompute import SerialRecompute
from application.ports.repositories.serial_repository import SerialRepository, SerialUpdate
from application.services._merge import check_merge_pair
from domain.errors import NotFoundError, ValidationError
from domain.serials.issns import SerialIssn
from domain.serials.serial import ManualField, SerialEdit, SerialType


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
    return changes


class SerialService:
    """Écritures sur les revues : édition, aperçu d'un changement de type, fusion.

    L'aperçu ouvre un `SAVEPOINT` dans la transaction de `conn`.
    """

    def __init__(
        self, *, serials: SerialRepository, recompute: SerialRecompute, conn: Connection
    ) -> None:
        self._serials = serials
        self._recompute = recompute
        self._conn = conn

    def update_serial(self, serial_id: int, update: SerialUpdate) -> int:
        """Charge la revue, applique les champs fournis (`Serial.edit`) et l'écrit. Si son type ou son modèle open access change, rejoue les corrections de ses publications : leur type suit celui de la revue, leur statut diamant son modèle open access. Renvoie le nombre de publications dont le type change.

        Un `null` sur un champ obligatoire (titre, type, caractère académique) vaut champ non fourni. L'événement d'audit contient seulement les champs soumis.

        Lève `ValidationError` si aucun champ n'est fourni ou si les ISSN sont invalides, `NotFoundError` si la revue n'existe pas.
        """
        if not update.model_fields_set:
            raise ValidationError("Aucun champ à mettre à jour")

        serial = self._serials.find_by_id(serial_id)
        if serial is None:
            raise NotFoundError(f"Revue {serial_id} introuvable")

        changed = serial.edit(**_serial_edit(update))
        self._serials.save(serial)
        emit_event(
            "serial.updated",
            "serial",
            serial_id,
            update.model_dump(exclude_unset=True, mode="json"),
        )
        if not changed & {ManualField.SERIAL_TYPE, ManualField.OA_MODEL}:
            return 0
        return self.requalify_publications_for_serial(serial_id)

    def preview_type_change_impact(self, serial_id: int, serial_type: SerialType) -> int:
        """Compte les publications de la revue dont le type changerait avec le type de revue donné.

        Applique réellement l'édition (`update_serial`) dans un `SAVEPOINT` annulé : l'aperçu emprunte le chemin exact de l'édition, et aucune écriture ne survit, ni aucun événement d'audit. Lève `NotFoundError` sur une revue inconnue, comme l'édition simulée.
        """
        savepoint = self._conn.begin_nested()
        try:
            with discarded_events():
                return self.update_serial(serial_id, SerialUpdate(serial_type=serial_type))
        finally:
            savepoint.rollback()

    def merge_serials(self, target_id: int, source_id: int) -> None:
        """Fusionne la revue source dans la revue cible, par le pipeline, qui requalifie les publications absorbées.

        Lève `ValidationError` sur deux identifiants égaux, `NotFoundError` sur une revue introuvable.
        """
        check_merge_pair(target_id, source_id, self._serials.find_by_id, label="Revue")
        self._recompute.merge_serials(target_id, source_id)
        emit_event("serial.merged", "serial", target_id, {"source_id": source_id})

    def requalify_publications_for_serial(self, serial_id: int) -> int:
        """Requalifie, par le pipeline, le `doc_type` des publications d'une revue après un changement de son `serial_type`.

        L'appelant a écrit le nouveau type dans la même transaction. Renvoie le nombre de publications dont le `doc_type` change, et émet l'audit `serial.type_requalified` si ce nombre est positif.
        """
        changed = self._recompute.requalify_publications(serial_id)
        if changed > 0:
            emit_event(
                "serial.type_requalified",
                "serial",
                serial_id,
                {"count": changed},
            )
        return changed
