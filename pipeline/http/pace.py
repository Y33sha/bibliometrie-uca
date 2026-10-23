"""Rythme des requêtes à une source : un plafond de débit commun à toutes ses requêtes, synchrones ou simultanées."""

from __future__ import annotations

import asyncio
import threading
import time


class Pace:
    """Plafond de débit : les départs sont réservés l'un après l'autre, espacés de `1 / max_per_second` seconde.

    Le plafond vaut pour toutes les requêtes, quel que soit le nombre de requêtes simultanées et leur temps de réponse. Une requête que l'ordonnancement retarde part après sa réservation, jamais avant : le nombre de départs sur une durée reste borné.
    """

    def __init__(self, max_per_second: float) -> None:
        self._interval_s = 1 / max_per_second
        self._next_start = 0.0
        self._lock = threading.Lock()

    def _reserve(self) -> float:
        """Réserve le prochain départ et rend l'attente qui le sépare de maintenant."""
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_start)
            self._next_start = start + self._interval_s
        return start - now

    def wait(self) -> None:
        """Attend le prochain départ autorisé et le réserve."""
        if (delay := self._reserve()) > 0:
            time.sleep(delay)

    async def wait_async(self) -> None:
        """Attend le prochain départ autorisé et le réserve, sans bloquer la boucle d'événements."""
        if (delay := self._reserve()) > 0:
            await asyncio.sleep(delay)
