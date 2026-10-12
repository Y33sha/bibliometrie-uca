"""Port : recalculs, par le pipeline, des publications d'une revue après son édition ou sa fusion.

Implémenté par `pipeline.transformation.publishing.journals.journal_merge.JournalRecompute`.
"""

from typing import Protocol

from sqlalchemy import Connection


class JournalRecompute(Protocol):
    """Recalculs ciblés des publications d'une revue."""

    def requalify_publications(self, conn: Connection, journal_id: int) -> int:
        """Rejoue les corrections des `source_publications` de la revue et recalcule ses publications. Retourne le nombre de publications dont le `doc_type` change."""
        ...

    def merge_journals(self, conn: Connection, target_id: int, source_id: int) -> None:
        """Fusionne la revue `source_id` dans `target_id`, puis requalifie les publications absorbées contre le `journal_type` de la cible."""
        ...
