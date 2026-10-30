"""Issue d'une requête à une source pour un élément : valeur trouvée, absence confirmée, ou source indisponible.

Seule une absence confirmée autorise l'enregistrement de l'élément comme vérifié. Une source indisponible (réseau, 429 ou 5xx après les nouvelles tentatives, réponse illisible, circuit-breaker déclenché) laisse l'élément en attente du run suivant.
"""

from __future__ import annotations


class NotFound:
    """Absence confirmée : la source a répondu correctement, sans résultat."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NOT_FOUND"


class Unavailable:
    """Source indisponible : l'absence de l'élément reste incertaine."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "UNAVAILABLE"


NOT_FOUND = NotFound()
UNAVAILABLE = Unavailable()

type LookupOutcome[T] = T | NotFound | Unavailable
