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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Protocol

try:
    from tqdm import tqdm
    from tqdm.utils import disp_len

    # `tqdm` se verrouille par défaut sur un `multiprocessing.RLock`, soit un sémaphore du
    # système, qu'un processus interrompu laisse derrière lui. Le pipeline répartit son travail
    # entre threads, jamais entre processus : un verrou de threads suffit et ne laisse rien.
    tqdm.set_lock(threading.RLock())
except ImportError:  # `tqdm` est une dépendance de développement.
    tqdm = None  # type: ignore[assignment,misc]

JALON_INTERVALLE_S = 30.0
"""Délai entre deux jalons de journal, quand aucune barre ne s'affiche."""

FORMAT_BARRE = "{desc} {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt}  {elapsed}"
"""Barre réduite à l'avancement et au temps écoulé."""

FORMAT_BARRE_RETENUS = "{desc} {percentage:3.0f}% |{bar}| {retenus}/{total_fmt}  {elapsed}"
"""Barre dont le compteur porte les éléments retenus, quand le remplissage suit les parcourus."""


class FluxTexte(Protocol):
    """Ce qu'une barre et une ligne de journal écrivent en commun."""

    def write(self, texte: str, /) -> int: ...

    def flush(self) -> None: ...


EFFACE_FIN_DE_LIGNE = "\x1b[K"
"""Séquence effaçant du curseur à la fin de la ligne."""

EFFACE_BAS_DE_L_ECRAN = "\x1b[J"
"""Séquence effaçant du curseur au bas de l'écran."""


if tqdm is not None:

    class _Barre(tqdm):  # type: ignore[misc]
        """Barre dont le redessin résiste au redimensionnement du terminal.

        Un terminal rétréci reçoit une barre plus longue que sa largeur. Il la replie sur autant de lignes qu'il faut, et le redessin suivant les efface toutes.
        """

        def status_printer(self, flux: FluxTexte) -> Callable[[str], None]:
            """Réécrit la ligne en place : retour chariot, barre, effacement de ce qui suit.

            L'effacement passe par une séquence, qui occupe une colonne quelle que soit la largeur. Des espaces jusqu'à la longueur du redessin précédent déborderaient d'un terminal rétréci entre-temps, et le redessin d'après s'installerait sur ce débordement, laissant la barre précédente affichée au-dessus.

            Le curseur revient en début de ligne. Un terminal qui replie une ligne garde le curseur à la place qu'il occupe dans le texte : laissé en fin de barre, il passerait sur la dernière ligne du repli, hors de portée du redessin suivant.
            """
            longueur_precedente = 0

            def redessine(ligne: str) -> None:
                nonlocal longueur_precedente
                repliee = longueur_precedente > (self.ncols or 0)
                efface = EFFACE_BAS_DE_L_ECRAN if repliee else EFFACE_FIN_DE_LIGNE
                flux.write(f"\r{ligne}{efface}\r")
                flux.flush()
                longueur_precedente = disp_len(ligne)

            return redessine

    class _BarreRetenus(_Barre):
        """Barre offrant `{retenus}` à son format, à côté des champs que `tqdm` fournit."""

        retenus = 0

        @property
        def format_dict(self) -> dict[str, object]:
            return {**super().format_dict, "retenus": self.retenus}
else:
    _Barre = None  # type: ignore[assignment,misc]
    _BarreRetenus = None  # type: ignore[assignment,misc]

RAFRAICHISSEMENT_S = 0.1
"""Délai entre deux redessins de la barre à l'arrêt, pendant qu'une source répond."""

RAFRAICHISSEMENT_ATTENTE_S = 0.4
"""Délai entre deux points d'une attente : assez lent pour se suivre à l'œil."""

type Journal = logging.Logger | logging.LoggerAdapter[logging.Logger]
"""Ce qui accepte une ligne de journal : un logger, ou l'adaptateur qui le préfixe."""


_flux_barres: FluxTexte | None = None


def set_flux_barres(flux: FluxTexte | None) -> None:
    """Flux sur lequel les barres s'affichent, celui-là même qui porte les lignes de journal.

    Un flux commun permet à chacune d'effacer l'autre : sur deux flux distincts, les barres et les lignes se recouvrent.
    """
    global _flux_barres
    _flux_barres = flux


def ecrire_hors_barre(ligne: str, flux: FluxTexte) -> None:
    """Écrit `ligne` au-dessus des barres en cours, qui se redessinent ensuite.

    La ligne emporte de quoi effacer ce qui la suit : plus courte que la barre dont elle prend la place, elle en laisserait la fin derrière elle.
    """
    if tqdm is None:
        print(ligne, file=flux)
        return
    if _terminal_interactif():
        ligne = f"{ligne}{EFFACE_FIN_DE_LIGNE}"
    tqdm.write(ligne, file=flux)


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
        compte_retenus: bool = False,
    ) -> None:
        self._total = total
        self._libelle = libelle
        self._logger = logger
        self._intervalle_s = intervalle_s
        self._fait = 0
        self._retenus = 0
        self._compte_retenus = compte_retenus
        self._debut = time.perf_counter()
        self._fini = threading.Event()
        self._dernier_jalon = self._debut
        classe = _BarreRetenus if compte_retenus else _Barre
        self._barre = (
            classe(
                total=total,
                desc=libelle,
                bar_format=FORMAT_BARRE_RETENUS if compte_retenus else FORMAT_BARRE,
                leave=True,
                file=_flux_barres,
                dynamic_ncols=True,
            )
            if tqdm is not None and _terminal_interactif()
            else None
        )
        if self._barre is not None:
            threading.Thread(target=self._battre, daemon=True).start()

    def retient(self, n: int = 1) -> None:
        """Compte `n` éléments retenus de plus — trouvés, récupérés, corrigés selon la phase."""
        self._retenus += n
        if self._barre is not None and self._compte_retenus:
            self._barre.retenus = self._retenus

    def _battre(self) -> None:
        """Redessine la barre tant qu'elle vit : le temps écoulé avance même à l'arrêt.

        Une barre `tqdm` se redessine seulement quand elle avance. Une source qui répond lentement la figerait, sans distinguer l'attente de l'arrêt.

        Le redessin prend le verrou dont `tqdm.write` se sert : une ligne de journal efface les barres, s'écrit, puis les redessine, et un redessin qui s'y glisserait laisserait la fin de la barre derrière la ligne.
        """
        while not self._fini.wait(RAFRAICHISSEMENT_S):
            barre = self._barre
            if barre is None:
                return
            with tqdm.get_lock():
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
    compte_retenus: bool = False,
) -> Iterator[Progression]:
    """Ouvre une progression et la referme à la sortie du bloc.

    `compte_retenus` fait porter au compteur les éléments retenus, posés par `retient()`, quand la barre elle-même suit les éléments parcourus.
    """
    p = Progression(
        total, libelle, logger, intervalle_s=intervalle_s, compte_retenus=compte_retenus
    )
    try:
        yield p
    finally:
        p.ferme()


ETAPES_ATTENTE = ("", ".", "..", "...")
"""Points qui se suivent, pour montrer qu'un travail sans avancement mesurable se poursuit."""


class Attente:
    """Travail en cours dont l'avancement ne se mesure pas.

    En terminal, des points courent après le libellé tant que le travail dure, sur une ligne réécrite en place. Ailleurs, une ligne de journal annonce le travail.

    L'écriture va droit au flux : `tqdm` mesure un avancement, et il n'y en a pas ici. Aucune barre ne tourne pendant ce temps, la maintenance venant après les boucles de la phase.
    """

    def __init__(self, libelle: str, logger: Journal | None) -> None:
        self._libelle = libelle
        self._logger = logger
        self._conclusion = ""
        self._fini = threading.Event()
        self._flux = _flux_barres if _terminal_interactif() else None
        if self._flux is None:
            if logger is not None:
                logger.info("%s…", libelle)
            return
        self._ecrire(ETAPES_ATTENTE[0])
        threading.Thread(target=self._battre, daemon=True).start()

    def _ecrire(self, points: str) -> None:
        """Réécrit la ligne en place, le retour chariot ramenant le curseur à son début.

        La ligne emporte de quoi effacer ce qui la suit : plus courte que celle dont elle prend la place, elle en laisserait la fin derrière elle.
        """
        flux = self._flux
        if flux is not None:
            flux.write(f"\r{self._libelle}{points}{EFFACE_FIN_DE_LIGNE}")
            flux.flush()

    def _battre(self) -> None:
        """Fait courir les points tant que le travail dure."""
        etape = 0
        while not self._fini.wait(RAFRAICHISSEMENT_ATTENTE_S):
            etape = (etape + 1) % len(ETAPES_ATTENTE)
            self._ecrire(ETAPES_ATTENTE[etape])

    def conclut(self, texte: str) -> None:
        """Donne à la ligne le texte qu'elle gardera une fois le travail fini."""
        self._conclusion = texte

    def ferme(self) -> None:
        """Arrête les points en laissant sur la ligne le libellé, ou la conclusion posée."""
        self._fini.set()
        if self._flux is not None:
            self._libelle = self._conclusion or self._libelle
            self._ecrire("")
            self._flux.write("\n")
            self._flux.flush()
            self._flux = None
        elif self._conclusion and self._logger is not None:
            self._logger.info("%s", self._conclusion)


@contextmanager
def attente(libelle: str, logger: Journal | None) -> Iterator[Attente]:
    """Signale pendant tout le bloc qu'un travail se poursuit, sans en mesurer l'avancement.

    `conclut()` donne à la ligne le texte qu'elle gardera une fois le bloc terminé.
    """
    a = Attente(libelle, logger)
    try:
        yield a
    finally:
        a.ferme()
