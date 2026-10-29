"""Port : recalculs, par le pipeline, des publications d'une revue après son édition ou sa fusion.

Implémenté par `pipeline.transformation.publishing.serials.serial_merge.SerialRecompute`.
"""

from typing import Protocol


class SerialRecompute(Protocol):
    """Recalculs ciblés des publications d'une revue."""

    def requalify_publications(self, serial_id: int) -> int:
        """Rejoue les corrections des enregistrements sources de la revue et recalcule ses publications. Rend le nombre de publications dont le type change."""
        ...

    def merge_serials(self, target_id: int, source_id: int) -> None:
        """Fusionne la revue `source_id` dans `target_id`, puis requalifie les publications absorbées contre le `serial_type` de la cible."""
        ...
