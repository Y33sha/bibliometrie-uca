"""Utilitaire de mesure de performance pour les normaliseurs."""

import logging
import time

# Seuil au-delà duquel un document est jugé « lent » et loggé (par toutes les
# sources via `StepTimer.log_if_slow`).
SLOW_DOC_THRESHOLD_S = 0.5


class StepTimer:
    """Chronomètre par étape pour diagnostiquer les documents lents.

    Usage :
        t = StepTimer()
        # ... traitement publisher ...
        t.mark("publisher")
        # ... traitement journal ...
        t.mark("journal")
        t.log_if_slow("hal-12345", logger)
    """

    def __init__(self, threshold: float = SLOW_DOC_THRESHOLD_S):
        self._t0 = time.perf_counter()
        self._last = self._t0
        self._steps: list[tuple[str, float]] = []
        self._threshold = threshold

    def mark(self, label: str) -> None:
        now = time.perf_counter()
        self._steps.append((label, now - self._last))
        self._last = now

    def total(self) -> float:
        return time.perf_counter() - self._t0

    def log_if_slow(self, doc_id: str, logger: logging.Logger) -> None:
        total = self.total()
        if total > self._threshold:
            breakdown = " | ".join(f"{k}:{v:.3f}s" for k, v in self._steps)
            logger.info(f"  SLOW {doc_id} ({total:.3f}s) : {breakdown}")
