"""Port : primitif d'exécution parallèle de tâches indépendantes.

Injecté par le composition-root aux orchestrateurs des phases qui lancent plusieurs sous-tâches
concurrentes (`extract`, `cross_imports`). L'application ordonne « lance ces N thunks » sans
connaître le mécanisme (thread pool, propagation du contexte de log).

Satisfait par `infrastructure.concurrency.run_parallel`.
"""

from collections.abc import Callable
from typing import Protocol


class RunParallel(Protocol):
    """Lance des thunks étiquetés en parallèle et rend leurs résultats par étiquette.

    Chaque thunk s'exécute dans une copie du contexte courant (pour préserver l'estampille de phase
    des logs). Une exception non rattrapée par un thunk se propage (la phase échoue) ; un thunk qui
    veut signaler un cas sans échouer rend une valeur sentinelle.
    """

    def __call__[T](self, thunks: dict[str, Callable[[], T]]) -> dict[str, T]: ...
