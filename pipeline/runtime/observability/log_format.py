"""Formatage des messages de journal : bannière du run, cadre des phases, sections d'une phase, quantités accordées."""

from __future__ import annotations

import sys
import textwrap
from collections.abc import Iterable

from domain.sources.registry import LOOKUP_SOURCES, source_label
from infrastructure.observability.log import PHASE_MARKER
from pipeline.runtime.observability.logging_scope import ScopedOrPlainLogger

__all__ = [
    "BRANCH",
    "BRANCH_CONTINUATION",
    "LAST_BRANCH",
    "PHASE_TITLE_WIDTH",
    "SECTION",
    "banner",
    "breakdown",
    "inflect",
    "nothing_to_do",
    "phase_title",
    "quantity",
    "open_section",
    "setting",
    "source_branch",
]

SECTION = "▶ "
"""Ouvre une section d'une phase."""

BRANCH = "  ├─ "
"""Rattache une ligne à la section ouverte au-dessus."""

LAST_BRANCH = "  └─ "
"""Ferme la section : rattache sa dernière ligne."""

BRANCH_CONTINUATION = "  │  "
"""Rattache une ligne à la branche ouverte au-dessus, le trait vertical se prolongeant."""


_SOURCE_WIDTH = max(len(source_label(source)) for source in LOOKUP_SOURCES)
"""Colonne des noms de source, à la largeur du plus long."""


_SCOPE_WIDTH = len("2023-2026")
"""Colonne du périmètre d'une source, à la largeur d'une plage d'années."""


def source_branch(source: str, scope: str | None = None) -> str:
    """Renvoie le libellé de la barre d'avancement d'une source : sa branche, son nom, et le remplissage qui aligne les barres d'une même phase.

    `scope` ajoute une colonne pour le périmètre en cours, une année par exemple. Un périmètre vide garde la colonne, pour aligner une source sans périmètre sur les autres.
    """
    label = f"{BRANCH}{source_label(source):<{_SOURCE_WIDTH}}"
    if scope is None:
        return label
    return f"{label} {scope:<{_SCOPE_WIDTH}}"


def breakdown(
    logger: ScopedOrPlainLogger,
    header: str,
    rows: Iterable[tuple[int, str]],
    *,
    last: bool = True,
) -> None:
    """Écrit la ligne de branche `header`, puis une ligne par `(nombre, libellé)`, nombres alignés à droite.

    Sous une branche suivie d'autres lignes (`last` faux), le trait vertical longe le détail, et une ligne vide le sépare de la branche suivante.
    """
    rows = list(rows)
    margin = " " * len(LAST_BRANCH) if last else BRANCH_CONTINUATION
    logger.info("%s%s", LAST_BRANCH if last else BRANCH, header)
    width = max((len(str(count)) for count, _ in rows), default=0)
    for count, label in rows:
        logger.info("%s%s %s", margin, str(count).rjust(width), label)
    if not last:
        logger.info("%s", margin.rstrip())


def open_section(logger: ScopedOrPlainLogger, title: str, *args: object) -> None:
    """Ouvre une section : une ligne vide, puis son titre.

    Args:
        args: champs de `title`, comme pour tout message de journal.
    """
    line = f"{SECTION}{title}"
    logger.info("")
    logger.info(line, *args)


def nothing_to_do(logger: ScopedOrPlainLogger) -> None:
    """Ferme une section sans rien à traiter."""
    logger.info("%sRien à faire", LAST_BRANCH)


def inflect(n: int, singular: str, plural: str | None = None) -> str:
    """Renvoie « préfixe » ou « préfixes » selon `n`. Zéro prend le singulier.

    Args:
        plural: pluriel, quand il ne se forme pas par un `s` final.
    """
    if plural is None:
        plural = f"{singular}s"
    return singular if abs(n) <= 1 else plural


def quantity(n: int, singular: str, plural: str | None = None) -> str:
    """Renvoie « 1 préfixe » ou « 3 préfixes »."""
    return f"{n} {inflect(n, singular, plural)}"


PHASE_TITLE_WIDTH = 48
"""Largeur du texte dans le cadre d'un titre, la même pour tous."""


def _framed(lines: list[str]) -> list[str]:
    """Encadre `lines`, chacune repliée à la largeur du cadre.

    Un terminal reçoit un cadre de largeur constante, une sortie capturée deux filets horizontaux.
    """
    if not sys.stdout.isatty():
        return ["─" * 40, *lines, "─" * 40]

    wrapped_lines = [
        wrapped for line in lines for wrapped in textwrap.wrap(line, PHASE_TITLE_WIDTH)
    ]
    width = PHASE_TITLE_WIDTH + 4
    return [
        f"╔{'═' * width}╗",
        *[f"║  {line.ljust(width - 2)}║" for line in wrapped_lines],
        f"╚{'═' * width}╝",
    ]


def phase_title(name: str, label: str) -> list[str]:
    """Renvoie les lignes d'ouverture d'une phase : son nom et son libellé."""
    return _framed([f"{PHASE_MARKER}{name}", label])


PIPELINE_TITLE = (
    "┏┓ ╻┏┓ ╻  ╻┏━┓┏┳┓┏━╸╺┳╸┏━┓╻┏━╸",
    "┣┻┓┃┣┻┓┃  ┃┃ ┃┃┃┃┣╸  ┃ ┣┳┛┃┣╸",
    "┗━┛╹┗━┛┗━╸╹┗━┛╹ ╹┗━╸ ╹ ╹┗╸╹┗━╸",
)
"""« BIBLIOMETRIE » en caractères de filets, en tête de la bannière d'une exécution."""

_SETTING_KEY_WIDTH = 9
"""Largeur d'une clé de réglage et de ses points de conduite, dans la bannière."""


def setting(key: str, value: str) -> list[str]:
    """Renvoie les lignes « clé ···· valeur » de la bannière, la valeur repliée sous elle-même."""
    head = f"{key} {'·' * (_SETTING_KEY_WIDTH - len(key))} "
    wrapped = textwrap.wrap(value, PHASE_TITLE_WIDTH - len(head)) or [""]
    return [head + wrapped[0], *(" " * len(head) + continuation for continuation in wrapped[1:])]


def banner(settings: list[str]) -> list[str]:
    """Encadre le titre et les réglages d'une exécution, avec une ombre.

    Un terminal reçoit le cadre, au moins aussi large que celui d'une phase. Une sortie capturée reçoit deux filets et le titre en texte.
    """
    if not sys.stdout.isatty():
        return ["─" * 40, "PIPELINE BIBLIOMÉTRIQUE", *settings, "─" * 40]

    settings = [f"  {setting}" for setting in settings]
    drawing_width = max(map(len, PIPELINE_TITLE))
    width = max(
        PHASE_TITLE_WIDTH + 4, drawing_width + 4, *(len(setting) + 2 for setting in settings)
    )
    # Un même retrait pour toutes les lignes du dessin : centrées une à une, elles se décaleraient.
    indent = " " * ((width - drawing_width) // 2)
    body = ["", *(indent + line for line in PIPELINE_TITLE), "", *settings, ""]
    tab = "┤ PIPELINE ├"
    return [
        f"┌───{tab}{'─' * (width - 3 - len(tab))}┐",
        *(f"│{line.ljust(width)}│▒" for line in body),
        f"└{'─' * width}┘▒",
        f" {'▒' * (width + 2)}",
    ]
