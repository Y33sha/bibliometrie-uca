"""Types partagés par les ports d'extraction (zone neutre).

Permet aux adapters `infrastructure/sources/*/extract_*.py` et aux orchestrateurs `application/pipeline/extract/extract_*.py` de partager les mêmes value objects de retour sans dépendance circulaire.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class UpsertOutcome(StrEnum):
    """Issue de l'UPSERT d'une ligne `staging` unique, dérivée des signaux `(inserted, changed)` du helper canonique.

    - `NEW` : vraie insertion (`RETURNING (xmax = 0)`).
    - `UPDATED` : ligne existante dont le **contenu a changé** (`raw_data` réécrit, `raw_hash` distinct de celui en base).
    - `UNCHANGED` : ligne re-vue à contenu identique (seul `last_seen_at` bumpé).
    """

    NEW = "new"
    UPDATED = "updated"
    UNCHANGED = "unchanged"

    @classmethod
    def of(cls, *, inserted: bool, changed: bool) -> UpsertOutcome:
        """Classe le résultat d'`upsert_staging` : `inserted` prime, le `changed` d'une insertion étant sans objet."""
        if inserted:
            return cls.NEW
        return cls.UPDATED if changed else cls.UNCHANGED


@dataclass(frozen=True)
class BatchInsertCounts:
    """Résultat d'un `insert_batch`, ventilé en trois.

    - `new` : vraie insertion (`RETURNING (xmax = 0)`).
    - `updated` : row existante dont le **contenu a changé** (`raw_data` réécrit, `raw_hash` distinct de l'ancien — capté via une CTE qui lit l'ancien hash avant l'UPSERT, comparé au nouveau dans le `RETURNING`).
    - `unchanged` : row re-vue à contenu identique (seul `last_seen_at` bumpé).
    """

    new: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.new + self.updated + self.unchanged
