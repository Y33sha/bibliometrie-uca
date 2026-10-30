"""Service de la fusion manuelle de deux publications.

La fusion manuelle enregistre un verdict, relu par la réconciliation à chaque exécution du pipeline. Le service applique aussitôt ce verdict par les recalculs ciblés du pipeline (`PublicationRecompute`). Les contributions réalignées reçoivent la personne de leurs contributions sources d'avant la fusion (`merge_attributions`).
"""

from typing import NamedTuple

from sqlalchemy import Connection

from application.audit_log import discarded_events, emit_event
from application.ports.pipeline.publication_perimeter import PublicationPerimeterRecompute
from application.ports.pipeline.publication_recompute import PublicationRecompute
from application.ports.repositories.publication_merge_repository import (
    PublicationMergeRepository,
)
from application.services._merge import check_merge_pair
from domain.errors import ValidationError
from domain.publications.manual_merge import check_mergeable, merge_attributions


class MergeOutcome(NamedTuple):
    """Résultat d'une fusion manuelle de publications."""

    publication_id: int
    """Publication issue de la fusion."""
    conflicts: int
    """Nombre de contributions laissées sans personne : leurs contributions sources désignaient deux personnes."""


class PublicationMergeService:
    """Fusion manuelle de deux publications, et son aperçu.

    L'aperçu ouvre un `SAVEPOINT` dans la transaction de `conn`.
    """

    def __init__(
        self,
        *,
        merges: PublicationMergeRepository,
        recompute: PublicationRecompute,
        perimeter_recompute: PublicationPerimeterRecompute,
        conn: Connection,
    ) -> None:
        self._merges = merges
        self._recompute = recompute
        self._perimeter_recompute = perimeter_recompute
        self._conn = conn

    def merge(self, publication_id: int, other_id: int) -> MergeOutcome:
        """Fusionne les deux publications. La réconciliation choisit la publication conservée : la publication à DOI, si l'une des deux en a un.

        Raises:
            ValidationError: deux identifiants égaux, deux DOI distincts, ou réconciliation sans publication unique.
            NotFoundError: publication introuvable.
        """
        dois = self._merges.dois([publication_id, other_id])
        check_merge_pair(
            publication_id, other_id, lambda pid: pid if pid in dois else None, label="Publication"
        )
        check_mergeable(dois.values())

        publication_ids = [publication_id, other_id]
        source_record_ids = self._merges.source_record_ids(publication_ids)
        previous = self._merges.attributions(publication_ids)
        self._merges.record_manual_merge(source_record_ids)
        self._recompute.reconcile(source_record_ids)
        merged = self._merges.publications_of(source_record_ids)
        if len(merged) != 1:
            raise ValidationError(
                f"Fusion impossible : la réconciliation donne {len(merged)} publications"
            )
        merged_id = merged.pop()

        self._recompute.realign(merged_id)
        result = merge_attributions(previous, self._merges.contributions(merged_id))
        self._merges.write_attributions(merged_id, result.attributions)
        self._perimeter_recompute.refresh_publications([merged_id])
        emit_event(
            "publication.merged",
            "publication",
            merged_id,
            {"publication_ids": publication_ids, "conflicts": len(result.conflicts)},
        )
        return MergeOutcome(merged_id, len(result.conflicts))

    def preview_merge(self, publication_id: int, other_id: int) -> MergeOutcome:
        """Renvoie le résultat qu'aurait la fusion des deux publications.

        Applique réellement la fusion (`merge`) dans un `SAVEPOINT` annulé, sans conserver d'écriture ni d'événement d'audit. Lève les mêmes erreurs que `merge`.
        """
        savepoint = self._conn.begin_nested()
        try:
            with discarded_events():
                return self.merge(publication_id, other_id)
        finally:
            savepoint.rollback()
