"""Exécution parallèle de thunks étiquetés, un thread chacun."""

import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol


class RunParallel(Protocol):
    """Lance des thunks étiquetés en parallèle et renvoie leurs résultats par étiquette.

    Chaque thunk s'exécute dans une copie du contexte courant, qui garde l'estampille de phase des journaux. L'exception d'un thunk se propage : la phase échoue.
    """

    def __call__[T](self, thunks: dict[str, Callable[[], T]]) -> dict[str, T]: ...


def run_parallel[T](thunks: dict[str, Callable[[], T]]) -> dict[str, T]:
    """Exécute les thunks en parallèle et renvoie `{étiquette: résultat}` (ordre d'achèvement)."""
    if not thunks:
        return {}
    results: dict[str, T] = {}
    with ThreadPoolExecutor(max_workers=len(thunks)) as pool:
        # Une copie par thread : deux threads ne peuvent pas entrer dans un même `Context`.
        futures = {
            pool.submit(contextvars.copy_context().run, thunk): label
            for label, thunk in thunks.items()
        }
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results
