"""Délai minimal entre deux requêtes à une même source."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


class Throttle:
    """Délai minimal entre deux requêtes d'un client.

    Le délai court depuis la fin de la requête précédente : le temps passé entre deux requêtes (analyse, écriture, commit) en est décompté.
    """

    def __init__(self, delay: float) -> None:
        self._delay = delay
        self._last_request_at: float | None = None

    @contextmanager
    def request(self) -> Iterator[None]:
        """Attend le reste du délai, puis encadre la requête."""
        if self._last_request_at is not None:
            wait = self._delay - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        try:
            yield
        finally:
            self._last_request_at = time.monotonic()
