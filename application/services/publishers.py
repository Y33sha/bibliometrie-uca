"""Service des éditeurs : mise à jour et fusion de l'entité Publisher."""

from application.audit_log import emit_event
from application.ports.pipeline.publication_count import PublicationCountRecompute
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdate,
)
from application.ports.repositories.serial_repository import SerialRepository
from application.services._merge import check_merge_pair
from application.services.serials import SerialService
from domain.errors import (
    ConflictError,
    NotFoundError,
    PublisherMergeBlockedError,
    ValidationError,
)
from domain.publishers.members import crossref_member_conflict
from domain.publishers.merge import split_shared_title_pairs


class PublisherService:
    """Écritures sur les éditeurs. La fusion de deux éditeurs fusionne aussi leurs revues homonymes (`SerialService`)."""

    def __init__(
        self,
        *,
        publishers: PublisherRepository,
        serials: SerialRepository,
        serial_service: SerialService,
        publication_count_recompute: PublicationCountRecompute,
    ) -> None:
        self._publishers = publishers
        self._serials = serials
        self._serial_service = serial_service
        self._publication_count_recompute = publication_count_recompute

    def update_publisher(self, publisher_id: int, update: PublisherUpdate) -> None:
        """Applique les champs fournis à l'éditeur et l'enregistre.

        L'événement d'audit contient seulement les champs soumis.

        Raises:
            ValidationError: aucun champ fourni.
            NotFoundError: éditeur introuvable.
        """
        if not update.model_fields_set:
            raise ValidationError("Aucun champ à mettre à jour")

        publisher = self._publishers.find_by_id(publisher_id)
        if publisher is None:
            raise NotFoundError(f"Éditeur {publisher_id} introuvable")

        # Les champs de `PublisherUpdate` ont les noms des attributs de l'entité.
        champs = update.model_dump(exclude_unset=True, mode="json")
        for field_name, value in update.model_dump(exclude_unset=True).items():
            setattr(publisher, field_name, value)
        self._publishers.save(publisher)
        emit_event("publisher.updated", "publisher", publisher_id, champs)

    def merge_publishers(self, target_id: int, source_id: int) -> None:
        """Fusionne l'éditeur source dans l'éditeur cible, puis recalcule le `publication_count` de la cible.

        Les revues homonymes des deux éditeurs sont fusionnées d'abord.

        Raises:
            ValidationError: deux identifiants égaux.
            NotFoundError: éditeur introuvable.
            ConflictError: membres Crossref distincts de part et d'autre.
            PublisherMergeBlockedError: paire de revues homonymes aux ISSN contradictoires, ou doublon de titre chez l'un des éditeurs.
        """
        check_merge_pair(target_id, source_id, self._publishers.find_by_id, label="Éditeur")

        # Deux membres Crossref distincts désignent deux éditeurs distincts.
        if conflict := crossref_member_conflict(
            self._publishers.crossref_member_ids(target_id),
            self._publishers.crossref_member_ids(source_id),
        ):
            raise ConflictError(f"Fusion refusée, {conflict} (cible / source)")

        # Les revues homonymes des deux éditeurs sont fusionnées, sauf paire bloquante. L'erreur contient toutes les paires bloquantes, affichées ensemble par l'interface.
        mergeable_pairs, blockers = split_shared_title_pairs(
            self._serials.find_shared_title_serial_pairs(target_id, source_id)
        )
        if blockers:
            raise PublisherMergeBlockedError(blockers)

        for pair in mergeable_pairs:
            self._serial_service.merge_serials(pair.target_serial_id, pair.source_serial_id)

        # Reprise des données de l'éditeur absorbé, selon leur règle de fusion.
        self._publishers.merge_publisher_into(target_id, source_id)
        self._publication_count_recompute.refresh_publisher_publication_count(target_id)

        emit_event("publisher.merged", "publisher", target_id, {"source_id": source_id})
