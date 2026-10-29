"""Formatage des messages de journal : quantités accordées, sous-étapes d'une phase."""

from __future__ import annotations

from collections.abc import Iterable

from domain.sources.registry import SOURCE_LABELS, source_label
from pipeline.runtime.observability.logging_scope import ScopedOrPlainLogger

STEP = "▶ "
"""Ouvre une sous-étape d'une phase."""

BRANCH = "  ├─ "
"""Rattache une ligne à la sous-étape ouverte au-dessus."""

LAST_BRANCH = "  └─ "
"""Ferme la sous-étape : rattache sa dernière ligne."""

BRANCH_CONTINUATION = "  │  "
"""Rattache une ligne à la branche ouverte au-dessus, le trait vertical se prolongeant."""


_SOURCE_WIDTH = max(len(label) for label in SOURCE_LABELS.values())
"""Colonne des noms de source, à la largeur du plus long."""


_SCOPE_WIDTH = len("2023-2026")
"""Colonne du périmètre d'une source, à la largeur d'une plage d'années."""


def source_branch(source: str, scope: str | None = None) -> str:
    """Libellé de la barre d'avancement d'une source : sa branche, son nom, et le remplissage qui aligne les barres d'une même phase les unes sous les autres.

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
    """Ligne de branche `header`, puis une ligne par `(nombre, libellé)`, nombres alignés à droite. Sous une branche suivie d'autres lignes (`last` faux), le trait vertical longe le détail, et une ligne vide le sépare de la branche suivante."""
    rows = list(rows)
    margin = " " * len(LAST_BRANCH) if last else BRANCH_CONTINUATION
    logger.info("%s%s", LAST_BRANCH if last else BRANCH, header)
    width = max((len(str(count)) for count, _ in rows), default=0)
    for count, label in rows:
        logger.info("%s%s %s", margin, str(count).rjust(width), label)
    if not last:
        logger.info("%s", margin.rstrip())


def step(logger: ScopedOrPlainLogger, title: str, *args: object) -> None:
    """Ouvre une sous-étape : une ligne vide la détache de ce qui précède, puis son titre.

    `args` complète les champs de `title`, comme pour tout message de journal.
    """
    line = f"{STEP}{title}"
    logger.info("")
    logger.info(line, *args)


def nothing_to_do(logger: ScopedOrPlainLogger, subject: str | None = None) -> None:
    """Ferme une sous-étape qui n'a rien à traiter. `subject` nomme la sous-étape quand l'étape en compte plusieurs."""
    logger.info("%s%s", LAST_BRANCH, f"{subject} : rien à faire" if subject else "Rien à faire")


def inflect(n: int, singular: str, plural: str | None = None) -> str:
    """Renvoie « préfixe » ou « préfixes » selon `n`. Zéro prend le singulier, comme le veut le français.

    `plural` couvre les formes que le `s` final ne donne pas.
    """
    if plural is None:
        plural = f"{singular}s"
    return singular if abs(n) <= 1 else plural


def quantity(n: int, singular: str, plural: str | None = None) -> str:
    """Renvoie « 1 préfixe » ou « 3 préfixes »."""
    return f"{n} {inflect(n, singular, plural)}"


__all__ = [
    "BRANCH",
    "BRANCH_CONTINUATION",
    "LAST_BRANCH",
    "STEP",
    "inflect",
    "nothing_to_do",
    "quantity",
    "source_branch",
    "step",
]
