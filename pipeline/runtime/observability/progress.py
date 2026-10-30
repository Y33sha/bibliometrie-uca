"""Avancement d'une boucle de traitement, affiché ou journalisé.

En terminal, une barre montre l'avancement. Sans terminal, ou sans `tqdm` installé, des jalons s'écrivent au journal à intervalle fixe, avec le débit. Sans `logger`, seule la barre s'affiche.

Usage :
    with track_progress(total=len(dois), label="crossref", logger=log) as progress:
        for batch in batches:
            process(batch)
            progress.advance(len(batch))
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

    # `tqdm` se verrouille par défaut sur un `multiprocessing.RLock`, soit un sémaphore du système, laissé en place par un processus interrompu. Seul le processus principal du pipeline affiche une barre : un verrou de threads suffit et ne laisse rien.
    tqdm.set_lock(threading.RLock())
except ImportError:  # `tqdm` est une dépendance de développement.
    tqdm = None

MILESTONE_INTERVAL_S = 30.0
"""Délai entre deux jalons de journal, quand aucune barre ne s'affiche."""

LINE_WIDTH = 80
"""Largeur maximale d'une barre, en colonnes. Une fenêtre plus étroite l'emporte : une ligne plus longue que la fenêtre s'y replierait, décalant les barres voisines."""

COUNTER_WIDTH = 13
"""Colonne du compteur, à la largeur de `435758/435758`. Largeur fixe, comme le nom de la source à gauche : le remplissage a donc aussi une largeur fixe, et les barres d'une même phase ont la même longueur."""

BAR_FORMAT = "{desc} {percentage:3.0f}% |{bar}| {counter} {elapsed}"
"""Barre réduite à l'avancement et au temps écoulé."""

KEPT_BAR_FORMAT = BAR_FORMAT
"""Barre dont le compteur donne les éléments retenus, quand le remplissage suit les parcourus."""


class TextStream(Protocol):
    """Flux d'écriture commun aux barres et aux lignes de journal."""

    def write(self, s: str, /) -> int: ...

    def flush(self) -> None: ...


class WritableStream(Protocol):
    """Flux confié par `tqdm` au redessin d'une barre. Seule l'écriture est garantie."""

    def write(self, s: str, /) -> object: ...


CLEAR_TO_END_OF_LINE = "\x1b[K"
"""Séquence effaçant du curseur à la fin de la ligne."""

CLEAR_TO_END_OF_SCREEN = "\x1b[J"
"""Séquence effaçant du curseur au bas de l'écran."""


def _counter_column(done: object, total: object) -> str:
    """Renvoie `done/total` à la largeur de la colonne, le total inconnu s'écrivant `?`."""
    return f"{done}/{total if total is not None else '?'}".ljust(COUNTER_WIDTH)


if tqdm is not None:
    # `tqdm` est générique dans ses stubs seulement : `tqdm[str]` lèverait à l'exécution.
    class _Bar(tqdm):  # pyrefly: ignore[implicit-any-type-argument]
        """Barre dont le redessin résiste au redimensionnement du terminal.

        Un terminal rétréci reçoit une barre plus longue que sa largeur. Il la replie sur autant de lignes qu'il faut, et le redessin suivant les efface toutes.
        """

        kept = 0
        """Éléments retenus, affichés par `_KeptBar`."""

        @property
        def format_dict(self) -> dict[str, object]:
            """Champs du format, avec le compteur complété et la largeur bornée.

            `{counter}` occupe une colonne fixe, donc le remplissage aussi : deux sources aux volumes différents tracent des barres de même longueur.

            Une source peut renvoyer plus d'éléments que le total qu'elle annonce. Le total affiché suit alors le compteur : `tqdm` traiterait un compteur supérieur au total comme un total inconnu, à 0 %.
            """
            fields: dict[str, object] = dict(super().format_dict)
            n, total = fields.get("n"), fields.get("total")
            if isinstance(n, int | float) and isinstance(total, int | float) and n > total:
                fields["total"] = n
            width = fields.get("ncols")
            if isinstance(width, int):
                # `self.ncols` sert aussi au redessin, qui compare la longueur écrite à la largeur.
                self.ncols = min(width, LINE_WIDTH)
                fields["ncols"] = self.ncols
            fields["counter"] = self._counter(fields)
            return fields

        def _counter(self, fields: dict[str, object]) -> str:
            """Renvoie les éléments parcourus sur le total, complétés à la largeur de la colonne."""
            return _counter_column(fields["n"], fields["total"])

        def status_printer(self, file: WritableStream) -> Callable[[str], None]:
            """Renvoie la fonction de redessin, qui réécrit la ligne en place : retour chariot, barre, effacement de la suite.

            L'effacement passe par une séquence, qui occupe une colonne quelle que soit la largeur. Des espaces jusqu'à la longueur du redessin précédent déborderaient d'un terminal rétréci entre-temps. Le redessin suivant s'écrirait sous ce débordement, et la barre précédente resterait affichée au-dessus.

            Le curseur revient en début de ligne. Un terminal qui replie une ligne garde le curseur à la place qu'il occupe dans le texte : laissé en fin de barre, il passerait sur la dernière ligne du repli, hors de portée du redessin suivant.
            """
            previous_length = 0
            flush = getattr(file, "flush", None)

            def redraw(line: str) -> None:
                nonlocal previous_length
                wrapped = previous_length > (self.ncols or 0)
                clear = CLEAR_TO_END_OF_SCREEN if wrapped else CLEAR_TO_END_OF_LINE
                file.write(f"\r{line}{clear}\r")
                if flush is not None:
                    flush()
                previous_length = disp_len(line)

            return redraw

    class _KeptBar(_Bar):
        """Barre dont le compteur donne les éléments retenus, quand le remplissage suit les parcourus."""

        def _counter(self, fields: dict[str, object]) -> str:
            return _counter_column(self.kept, fields["total"])
else:
    _Bar = None
    _KeptBar = None

REFRESH_S = 0.1
"""Délai entre deux redessins de la barre à l'arrêt, pendant qu'une source répond."""

WAITING_REFRESH_S = 0.4
"""Délai entre deux points d'une attente : assez lent pour se suivre à l'œil."""

type LoggerLike = logging.Logger | logging.LoggerAdapter[logging.Logger]
"""Destination d'une ligne de journal : un logger, ou l'adaptateur qui le préfixe."""


_bar_stream: TextStream | None = None


def set_bar_stream(stream: TextStream | None) -> None:
    """Désigne le flux des barres, le même que celui des lignes de journal.

    Sur un flux commun, les barres et les lignes s'effacent mutuellement. Sur deux flux distincts, elles se recouvrent.
    """
    global _bar_stream
    _bar_stream = stream


def write_above_bars(line: str, stream: TextStream) -> None:
    """Écrit `line` au-dessus des barres en cours, puis les barres se redessinent.

    En terminal, la ligne se termine par un effacement de la fin de ligne : plus courte que la barre précédente, elle laisserait la fin de la barre affichée.
    """
    if tqdm is None:
        print(line, file=stream)
        return
    if _interactive_terminal():
        line = f"{line}{CLEAR_TO_END_OF_LINE}"
    tqdm.write(line, file=stream)


def _interactive_terminal() -> bool:
    """Indique si la sortie standard est un terminal."""
    try:
        return sys.stdout.isatty()
    except AttributeError, ValueError:
        return False


class Progress:
    """Avancement d'une boucle, affiché selon les capacités de la sortie."""

    def __init__(
        self,
        total: int | None,
        label: str,
        logger: LoggerLike | None,
        *,
        interval_s: float = MILESTONE_INTERVAL_S,
        count_kept: bool = False,
        erase: bool = False,
    ) -> None:
        self._total = total
        self._erase = erase
        self._label = label
        self._logger = logger
        self._interval_s = interval_s
        self._done = 0
        self._kept = 0
        self._count_kept = count_kept
        self._start = time.perf_counter()
        self._finished = threading.Event()
        self._last_milestone = self._start
        bar_class = _KeptBar if count_kept else _Bar
        self._bar = (
            bar_class(
                total=total,
                desc=label,
                bar_format=KEPT_BAR_FORMAT if count_kept else BAR_FORMAT,
                # `close` écrit elle-même la dernière image de la barre : `tqdm` la laisserait en tête du bloc des barres concurrentes, sur la ligne d'une autre barre.
                leave=False,
                file=_bar_stream,
                dynamic_ncols=True,
            )
            if bar_class is not None and _interactive_terminal()
            else None
        )
        if self._bar is not None:
            threading.Thread(target=self._tick, daemon=True).start()

    def keep(self, n: int = 1) -> None:
        """Compte `n` éléments retenus de plus : trouvés, récupérés ou corrigés selon la phase."""
        self._kept += n
        if self._bar is not None and self._count_kept:
            self._bar.kept = self._kept

    def _tick(self) -> None:
        """Redessine la barre tant qu'elle est ouverte : le temps écoulé avance même à l'arrêt.

        Une barre `tqdm` se redessine seulement quand elle avance. Une source qui répond lentement la figerait, sans distinguer l'attente de l'arrêt.

        Le redessin prend le verrou de `tqdm.write` : une ligne de journal efface les barres, s'écrit, puis les redessine. Un redessin intercalé laisserait la fin de la barre derrière la ligne.
        """
        while not self._finished.wait(REFRESH_S):
            bar = self._bar
            if bar is None:
                return
            with bar.get_lock():
                bar.refresh()

    def set_total(self, total: int) -> None:
        """Fixe le total, connu dès une première réponse."""
        self._total = total
        if self._bar is not None:
            self._bar.total = total
            self._bar.refresh()

    def relabel(self, label: str) -> None:
        """Change le libellé de la barre et des jalons, pour suivre le périmètre en cours."""
        self._label = label
        bar = self._bar
        if bar is not None:
            with bar.get_lock():
                bar.set_description_str(label)

    def advance(self, n: int = 1) -> None:
        """Compte `n` unités traitées de plus."""
        self._done += n
        if self._bar is not None:
            self._bar.update(n)
            return
        now = time.perf_counter()
        if now - self._last_milestone >= self._interval_s:
            self._last_milestone = now
            self._milestone(now)

    def _milestone(self, now: float) -> None:
        """Écrit une ligne d'avancement au journal."""
        if self._logger is None:
            return
        elapsed = now - self._start
        rate = self._done / elapsed if elapsed > 0 else 0.0
        share = f" ({self._done * 100 // self._total} %)" if self._total else ""
        self._logger.info(
            "%s : %d/%s%s — %.0f/s",
            self._label,
            self._done,
            self._total if self._total is not None else "?",
            share,
            rate,
        )

    def close(self) -> None:
        """Retire la barre. Sa dernière image reste au-dessus des barres encore actives, sauf avec `erase`.

        La dernière image s'écrit comme une ligne de journal : effacement des barres, écriture, redessin. `tqdm` l'écrirait en tête du bloc des barres, sur la ligne d'une autre barre, et décalerait les suivantes d'une ligne.
        """
        self._finished.set()
        bar = self._bar
        if bar is None:
            return
        self._bar = None
        with bar.get_lock():
            last_frame = str(bar)
            bar.close()
            if not self._erase:
                write_above_bars(last_frame, _bar_stream or sys.stderr)

    def __enter__(self) -> Progress:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


@contextmanager
def track_progress(
    total: int | None,
    label: str,
    logger: LoggerLike | None,
    *,
    interval_s: float = MILESTONE_INTERVAL_S,
    count_kept: bool = False,
    erase: bool = False,
) -> Iterator[Progress]:
    """Ouvre un suivi d'avancement et le referme à la sortie du bloc.

    Args:
        count_kept: le compteur donne les éléments retenus (`keep()`), le remplissage suit les éléments parcourus.
        erase: retire la barre sans trace à la fermeture, quand une ligne de bilan prend sa place.
    """
    progress = Progress(
        total,
        label,
        logger,
        interval_s=interval_s,
        count_kept=count_kept,
        erase=erase,
    )
    try:
        yield progress
    finally:
        progress.close()


WAITING_DOTS = ("", ".", "..", "...")
"""Points successifs, signe de la poursuite d'un travail sans avancement mesurable."""


class Waiting:
    """Travail en cours à avancement non mesurable.

    En terminal, des points défilent après le libellé tant que le travail dure, sur une ligne réécrite en place. Ailleurs, une ligne de journal annonce le travail.

    L'écriture va directement au flux, sans `tqdm` : il n'y a aucun avancement à mesurer. Aucune barre n'est active pendant l'attente : la maintenance suit les boucles de la phase.
    """

    def __init__(self, label: str, logger: LoggerLike | None) -> None:
        self._label = label
        self._logger = logger
        self._conclusion = ""
        self._erase = False
        self._finished = threading.Event()
        self._stream = _bar_stream if _interactive_terminal() else None
        if self._stream is None:
            if logger is not None:
                logger.info("%s…", label)
            return
        self._write(WAITING_DOTS[0])
        threading.Thread(target=self._tick, daemon=True).start()

    def _write(self, dots: str) -> None:
        """Réécrit la ligne en place, après un retour chariot.

        La ligne se termine par un effacement de la fin de ligne : plus courte que la précédente, elle laisserait la fin de la précédente affichée.
        """
        stream = self._stream
        if stream is not None:
            stream.write(f"\r{self._label}{dots}{CLEAR_TO_END_OF_LINE}")
            stream.flush()

    def _tick(self) -> None:
        """Fait défiler les points tant que le travail dure."""
        index = 0
        while not self._finished.wait(WAITING_REFRESH_S):
            index = (index + 1) % len(WAITING_DOTS)
            self._write(WAITING_DOTS[index])

    def conclude(self, text: str) -> None:
        """Fixe le texte final de la ligne."""
        self._conclusion = text

    def erase(self) -> None:
        """Marque la ligne à effacer à la fin du travail."""
        self._erase = True

    def close(self) -> None:
        """Arrête les points, puis laisse sur la ligne le libellé ou la conclusion, ou efface la ligne.

        En terminal, la ligne laissée va aussi au journal, masquée au terminal (`detail`).
        """
        self._finished.set()
        if self._stream is not None:
            if self._erase:
                self._stream.write(f"\r{CLEAR_TO_END_OF_LINE}")
            else:
                self._label = self._conclusion or self._label
                self._write("")
                self._stream.write("\n")
                if self._logger is not None:
                    self._logger.info("%s", self._label, extra={"detail": True})
            self._stream.flush()
            self._stream = None
        elif self._conclusion and not self._erase and self._logger is not None:
            self._logger.info("%s", self._conclusion)


@contextmanager
def waiting(label: str, logger: LoggerLike | None) -> Iterator[Waiting]:
    """Signale un travail en cours pendant tout le bloc, sans mesure d'avancement."""
    w = Waiting(label, logger)
    try:
        yield w
    finally:
        w.close()
