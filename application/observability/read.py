"""Calculs de lecture sur les exécutions de phase : écart de durée au médian.

Pur, sans I/O. La comparaison de durée se fait au médian historique de la même
phase, fourni par l'appelant (issu d'une requête) ; aucun seuil n'est posé, seul
le rapport est exposé pour l'affichage — l'œil juge une phase anormalement lente.
Les volumes d'entrée et de sortie (avant/après) sont affichés tels quels ; on n'en
dérive pas de ratio de rendement, peu comparable d'une phase à l'autre.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median


def median_duration(durations: Sequence[float]) -> float | None:
    """Médian des durées historiques d'une phase, ou `None` si l'historique est vide."""
    return float(median(durations)) if durations else None


def duration_ratio(duration_s: float, historical_median_s: float | None) -> float | None:
    """Rapport de la durée courante au médian historique (> 1 = plus lent que
    d'habitude). `None` sans historique exploitable."""
    if historical_median_s is None or historical_median_s == 0:
        return None
    return duration_s / historical_median_s
