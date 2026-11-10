"""Pagination de plusieurs requêtes en parallèle.

Chaque worker prend une requête, suit ses pages, puis passe à la suivante. Les pages arrivent au thread appelant par une file bornée, donc le nombre de pages en mémoire reste borné. Les callbacks s'exécutent dans le thread appelant : la `Connection` SQLAlchemy synchrone n'est pas thread-safe.
"""

from __future__ import annotations

import contextvars
import queue
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pipeline.http.circuit_breaker import SourceUnavailableError, source_tripped
from pipeline.ingestion.common.pages import Page


@dataclass(frozen=True, slots=True)
class _PageReceived[Item]:
    item: Item
    page: Page


@dataclass(frozen=True, slots=True)
class _ItemEnded[Item]:
    item: Item
    error: Exception | None


class _WorkerDone:
    pass


type _Message[Item] = _PageReceived[Item] | _ItemEnded[Item] | _WorkerDone


class _Workers[Item]:
    """Workers qui suivent les pages des requêtes en attente et les déposent dans `received`."""

    def __init__(
        self,
        items: Sequence[Item],
        fetch_page: Callable[[Item, str | None], Page],
        max_concurrent: int,
    ) -> None:
        self._fetch_page = fetch_page
        self._pending: queue.SimpleQueue[Item] = queue.SimpleQueue()
        for item in items:
            self._pending.put(item)
        self.received: queue.Queue[_Message[Item]] = queue.Queue(maxsize=max_concurrent)
        """File bornée : un worker attend que le thread appelant ait traité les pages en attente."""
        self._stop = threading.Event()
        self.running = max(1, min(max_concurrent, len(items)))

    def start(self) -> None:
        for _ in range(self.running):
            # Une copie du contexte par thread : le circuit-breaker de la source et l'estampille des journaux suivent.
            threading.Thread(
                target=contextvars.copy_context().run, args=(self._work,), daemon=True
            ).start()

    def stop(self) -> None:
        """Arrête les workers et attend leur fin, en vidant la file pour débloquer ceux qui y déposent."""
        self._stop.set()
        while self.running:
            if isinstance(self.received.get(), _WorkerDone):
                self.running -= 1

    def _work(self) -> None:
        try:
            while not self._stop.is_set() and not source_tripped():
                try:
                    item = self._pending.get_nowait()
                except queue.Empty:
                    return
                self.received.put(_ItemEnded(item, self._paginate(item)))
        finally:
            self.received.put(_WorkerDone())

    def _paginate(self, item: Item) -> Exception | None:
        """Suit les pages de `item` et renvoie l'exception qui interrompt la pagination."""
        token: str | None = None
        try:
            while not self._stop.is_set():
                page = self._fetch_page(item, token)
                self.received.put(_PageReceived(item, page))
                if not page.records or page.next_token is None:
                    return None
                token = page.next_token
        except Exception as e:  # noqa: BLE001 — l'erreur passe au thread appelant
            return e
        return None


def paginate_concurrently[Item](
    items: Sequence[Item],
    fetch_page: Callable[[Item, str | None], Page],
    *,
    max_concurrent: int,
    on_page: Callable[[Item, Page], None],
    on_end: Callable[[Item, Exception | None], None],
) -> None:
    """Suit les pages de chaque requête de `items` avec `max_concurrent` workers.

    `fetch_page` reçoit la requête et le jeton de la page suivante, `None` pour la première. Une page vide ou sans jeton clôt la pagination de la requête. `on_page` reçoit chaque page, dans l'ordre de la pagination de sa requête. `on_end` reçoit la fin de chaque requête, avec l'exception qui l'a interrompue.

    Une `SourceUnavailableError`, ou le circuit-breaker de la source coupé, arrête tous les workers ; l'erreur se propage. Une exception d'un callback arrête aussi les workers, puis se propage.
    """
    workers = _Workers(items, fetch_page, max_concurrent)
    workers.start()
    try:
        while workers.running:
            match workers.received.get():
                case _WorkerDone():
                    workers.running -= 1
                case _PageReceived(item, page):
                    on_page(item, page)
                case _ItemEnded(item, SourceUnavailableError() as error):
                    on_end(item, error)
                    raise error
                case _ItemEnded(item, error):
                    on_end(item, error)
    finally:
        workers.stop()
