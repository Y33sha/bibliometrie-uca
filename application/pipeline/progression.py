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
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Protocol

try:
    from tqdm import tqdm
except ImportError:  # `tqdm` est une dépendance de développement.
    tqdm = None  # type: ignore[assignment,misc]

JALON_INTERVALLE_S = 30.0
"""Délai entre deux jalons de journal, quand aucune barre ne s'affiche."""

FORMAT_BARRE = "{desc} {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}  {elapsed}"
"""Barre réduite à l'avancement et au temps écoulé."""

RAFRAICHISSEMENT_S = 0.1
"""Délai entre deux redessins de la barre à l'arrêt, pendant qu'une source répond."""

type Journal = logging.Logger | logging.LoggerAdapter[logging.Logger]
"""Ce qui accepte une ligne de journal : un logger, ou l'adaptateur qui le préfixe."""


class FluxTexte(Protocol):
    """Ce qu'une barre et une ligne de journal écrivent en commun."""

    def write(self, texte: str, /) -> int: ...

    def flush(self) -> None: ...


_flux_barres: FluxTexte | None = None


def set_flux_barres(flux: FluxTexte | None) -> None:
    """Flux sur lequel les barres s'affichent, celui-là même qui porte les lignes de journal.

    Un flux commun permet à chacune d'effacer l'autre : sur deux flux distincts, les barres et les lignes se recouvrent.
    """
    global _flux_barres
    _flux_barres = flux


def ecrire_hors_barre(ligne: str, flux: FluxTexte) -> None:
    """Écrit `ligne` au-dessus des barres en cours, qui se redessinent ensuite."""
    if tqdm is not None:
        tqdm.write(ligne, file=flux)
    else:
        print(ligne, file=flux)


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
        total: int | None,
        libelle: str,
        logger: Journal | None,
        *,
        intervalle_s: float = JALON_INTERVALLE_S,
    ) -> None:
        self._total = total
        self._libelle = libelle
        self._logger = logger
        self._intervalle_s = intervalle_s
        self._fait = 0
        self._debut = time.perf_counter()
        self._fini = threading.Event()
        self._dernier_jalon = self._debut
        self._barre = (
            tqdm(
                total=total,
                desc=libelle,
                bar_format=FORMAT_BARRE,
                leave=True,
                file=_flux_barres,
                dynamic_ncols=True,
            )
            if tqdm is not None and _terminal_interactif()
            else None
        )
        if self._barre is not None:
            threading.Thread(target=self._battre, daemon=True).start()

    def _battre(self) -> None:
        """Redessine la barre tant qu'elle vit : le temps écoulé avance même à l'arrêt.

        Une barre `tqdm` se redessine seulement quand elle avance. Une source qui répond lentement la figerait, sans distinguer l'attente de l'arrêt.
        """
        while not self._fini.wait(RAFRAICHISSEMENT_S):
            barre = self._barre
            if barre is None:
                return
            barre.refresh()

    def fixer_total(self, total: int) -> None:
        """Fixe le total qu'une première réponse révèle."""
        self._total = total
        if self._barre is not None:
            self._barre.total = total
            self._barre.refresh()

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
        part = f" ({self._fait * 100 // self._total} %)" if self._total else ""
        self._logger.info(
            "%s : %d/%s%s — %.0f/s",
            self._libelle,
            self._fait,
            self._total if self._total is not None else "?",
            part,
            debit,
        )

    def ferme(self) -> None:
        """Retire la barre."""
        self._fini.set()
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
    total: int | None,
    libelle: str,
    logger: Journal | None,
    *,
    intervalle_s: float = JALON_INTERVALLE_S,
) -> Iterator[Progression]:
    """Ouvre une progression et la referme à la sortie du bloc."""
    p = Progression(total, libelle, logger, intervalle_s=intervalle_s)
    try:
        yield p
    finally:
        p.ferme()
