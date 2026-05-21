"""Types partagés par les ports d'extraction (zone neutre).

Permet aux adapters `infrastructure/sources/*/extract_*.py` et aux orchestrateurs
`application/pipeline/extract/extract_*.py` de partager les mêmes value objects
de retour sans dépendance circulaire.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BatchInsertCounts:
    """Résultat d'un `insert_batch` : combien de rows réellement insérées vs mises à jour.

    Pour les SQL `ON CONFLICT DO UPDATE`, le distinguo est obtenu via
    `RETURNING (xmax = 0) AS inserted` (xmax=0 → vraie insertion, sinon update
    par ON CONFLICT).
    """

    new: int
    updated: int

    @property
    def total(self) -> int:
        return self.new + self.updated
