"""Types partagés par les ports d'extraction (zone neutre).

Permet aux adapters `infrastructure/sources/*/extract_*.py` et aux orchestrateurs
`application/pipeline/extract/extract_*.py` de partager les mêmes value objects
de retour sans dépendance circulaire.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BatchInsertCounts:
    """Résultat d'un `insert_batch`, ventilé en trois.

    - `new` : vraie insertion (`RETURNING (xmax = 0)`).
    - `updated` : row existante dont le **contenu a changé** (`raw_data` réécrit,
      `raw_hash` distinct de l'ancien — capté via une CTE qui lit l'ancien hash
      avant l'UPSERT, comparé au nouveau dans le `RETURNING`).
    - `unchanged` : row re-vue à contenu identique (seul `last_seen_at` bumpé).
    """

    new: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.new + self.updated + self.unchanged
