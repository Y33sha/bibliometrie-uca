"""Primitif d'exécution parallèle (`run_parallel`), et son type (`RunParallel`).

Lance chaque thunk dans un thread, dans une copie du contexte courant (`contextvars`) — sans quoi les logs des workers perdraient l'estampille de phase (nom de logger source au lieu de la phase). Une copie de contexte par worker : un même `Context` ne peut pas être entré par deux threads à la fois. Retourne le résultat de chaque thunk par étiquette ; l'exception d'un thunk qui échoue se propage (la phase échoue).
"""

import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol


class RunParallel(Protocol):
    """Lance des thunks étiquetés en parallèle et rend leurs résultats par étiquette.

    Chaque thunk s'exécute dans une copie du contexte courant (pour préserver l'estampille de phase des logs). Une exception non rattrapée par un thunk se propage (la phase échoue) ; un thunk qui veut signaler un cas sans échouer rend une valeur sentinelle.
    """

    def __call__[T](self, thunks: dict[str, Callable[[], T]]) -> dict[str, T]: ...


def run_parallel[T](thunks: dict[str, Callable[[], T]]) -> dict[str, T]:
    """Exécute les thunks en parallèle et rend `{étiquette: résultat}` (ordre d'achèvement)."""
    if not thunks:
        return {}
    results: dict[str, T] = {}
    with ThreadPoolExecutor(max_workers=len(thunks)) as pool:
        futures = {
            pool.submit(contextvars.copy_context().run, thunk): label
            for label, thunk in thunks.items()
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results
