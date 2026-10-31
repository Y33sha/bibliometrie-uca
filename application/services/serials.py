"""Service des publications en série : écritures sur l'entité Serial.

Le `serial_type` d'une revue alimente des règles de correction du `doc_type` de ses publications. Après une édition ou une fusion, le pipeline rejoue ces corrections (`SerialRecompute`).
"""

from sqlalchemy import Connection

from application.audit_log import discarded_events, emit_event
from application.ports.pipeline.serial_recompute import SerialRecompute
from application.ports.repositories.serial_repository import SerialRepository, SerialUpdate
from application.services._merge import check_merge_pair
from domain.errors import NotFoundError, ValidationError
from domain.serials.serial import ManualField, SerialEdit, SerialType


def _serial_edit(update: SerialUpdate) -> SerialEdit:
    """Renvoie les champs fournis de `update`, sous la forme reçue par l'entité."""
    provided = update.model_fields_set
    changes = SerialEdit()
    if "title" in provided and update.title is not None:
        changes["title"] = update.title
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
        """Applique les champs fournis à la revue (`Serial.edit`) et l'enregistre. Renvoie le nombre de publications à type modifié.

        Si le type ou le modèle open access de la revue change, les corrections de ses publications sont rejouées. Leur type suit celui de la revue, leur statut diamant son modèle open access.

        Un `null` sur un champ obligatoire (titre, type, caractère académique) vaut champ non fourni. L'événement d'audit contient seulement les champs soumis.

        Raises:
            ValidationError: aucun champ fourni.
            NotFoundError: revue introuvable.
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

        Applique réellement l'édition (`update_serial`) dans un `SAVEPOINT` annulé, sans conserver d'écriture ni d'événement d'audit. L'aperçu suit donc exactement le chemin de l'édition. Lève `NotFoundError` sur une revue inconnue.
        """
        savepoint = self._conn.begin_nested()
        try:
            with discarded_events():
                return self.update_serial(serial_id, SerialUpdate(serial_type=serial_type))
        finally:
            savepoint.rollback()

    def merge_serials(self, target_id: int, source_id: int) -> None:
        """Fusionne la revue source dans la revue cible par le pipeline, qui requalifie les publications absorbées.

        La revue source est sans ISSN : deux ISSN-L désignent deux revues. La fusion est gardée comme décision de rattachement par titre, relue par le rattachement des enregistrements sources.

        Raises:
            ValidationError: deux identifiants égaux, ou revue source à ISSN-L quand la cible en a un.
            NotFoundError: revue introuvable.
        """
        check_merge_pair(target_id, source_id, self._serials.find_by_id, label="Revue")
        source_issnl = self._serials.issnl_of(source_id)
        if source_issnl is not None and self._serials.issnl_of(target_id) is not None:
            raise ValidationError("Deux revues à ISSN-L distincts ne fusionnent pas")
        if source_issnl is None:
            self._serials.record_title_decision(source_id, target_id)
        self._recompute.merge_serials(target_id, source_id)
        emit_event("serial.merged", "serial", target_id, {"source_id": source_id})

    def requalify_publications_for_serial(self, serial_id: int) -> int:
        """Requalifie, par le pipeline, le `doc_type` des publications d'une revue après un changement de son `serial_type`.

        L'appelant a écrit le nouveau type dans la même transaction. Renvoie le nombre de publications à `doc_type` modifié. Émet l'événement d'audit `serial.type_requalified` si ce nombre est positif.
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
