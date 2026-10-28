"""Port : recalculs, par le pipeline, des publications touchées par une fusion manuelle.

Implémenté par `pipeline.transformation.publications.publication_recompute.PublicationRecompute`.
"""

from collections.abc import Sequence
from typing import Protocol


class PublicationRecompute(Protocol):
    """Recalculs ciblés de quelques publications."""

    def reconcile(self, source_record_ids: Sequence[int]) -> frozenset[int]:
        """Réconcilie le voisinage des enregistrements sources `source_record_ids` et recalcule les métadonnées consolidées des publications conservées. Rend ces publications."""
        ...

    def realign(self, publication_id: int) -> None:
        """Recalcule les contributions de la publication, puis leurs attributs."""
        ...
