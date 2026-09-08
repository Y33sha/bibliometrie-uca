"""Avancement d'une boucle de traitement, affiché ou journalisé.

En terminal, une barre montre l'avancement. Sans terminal, ou sans `tqdm` installé, des jalons partent au journal à intervalle fixe, avec le débit. Un `logger` absent laisse la barre seule.

Usage :
    with progression(total=len(dois), libelle="crossref", logger=log) as p:
        for lot in lots:
            traiter(lot)
            p.avance(len(lot))
"""

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType

try:
    from tqdm import tqdm
except ImportError:  # `tqdm` est une dépendance de développement.
    tqdm = None  # type: ignore[assignment,misc]

JALON_INTERVALLE_S = 30.0
"""Délai entre deux jalons de journal, quand aucune barre ne s'affiche."""

FORMAT_BARRE = "{desc} {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}  {elapsed}"
"""Barre réduite à l'avancement et au temps écoulé."""


def _terminal_interactif() -> bool:
    """Vrai quand la sortie standard est un terminal."""
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


class Progression:
    """Avancement d'une boucle, rendu selon ce que la sortie permet."""

    def __init__(
        self,
        total: int,
        libelle: str,
        logger: logging.Logger | None,
        *,
        intervalle_s: float = JALON_INTERVALLE_S,
    ) -> None:
        self._total = total
        self._libelle = libelle
        self._logger = logger
        self._intervalle_s = intervalle_s
        self._fait = 0
        self._debut = time.perf_counter()
        self._dernier_jalon = self._debut
        self._barre = (
            tqdm(total=total, desc=libelle, bar_format=FORMAT_BARRE, leave=True)
            if tqdm is not None and _terminal_interactif()
            else None
        )

    def avance(self, n: int = 1) -> None:
        """Compte `n` unités traitées de plus."""
        self._fait += n
        if self._barre is not None:
            self._barre.update(n)
            return
        maintenant = time.perf_counter()
        if maintenant - self._dernier_jalon >= self._intervalle_s:
            self._dernier_jalon = maintenant
            self._jalon(maintenant)

    def _jalon(self, maintenant: float) -> None:
        """Écrit une ligne d'avancement au journal."""
        if self._logger is None:
            return
        ecoule = maintenant - self._debut
        debit = self._fait / ecoule if ecoule > 0 else 0.0
        if self._total > 0:
            part = f" ({self._fait * 100 // self._total} %)"
        else:
            part = ""
        self._logger.info(
            "%s : %d/%d%s — %.0f/s", self._libelle, self._fait, self._total, part, debit
        )

    def ferme(self) -> None:
        """Retire la barre."""
        if self._barre is not None:
            self._barre.close()
            self._barre = None

    def __enter__(self) -> "Progression":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.ferme()


@contextmanager
def progression(
    total: int,
    libelle: str,
    logger: logging.Logger | None,
    *,
    intervalle_s: float = JALON_INTERVALLE_S,
) -> Iterator[Progression]:
    """Ouvre une progression et la referme à la sortie du bloc."""
    p = Progression(total, libelle, logger, intervalle_s=intervalle_s)
    try:
        yield p
    finally:
        p.ferme()
