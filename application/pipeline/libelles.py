"""Formatage des messages de journal : quantités accordées, sous-étapes d'une phase."""

from __future__ import annotations

from application.pipeline.logging_scope import ScopedOrPlainLogger
from domain.sources.registry import SOURCE_LABELS, source_label

ETAPE = "▶ "
"""Ouvre une sous-étape d'une phase."""

BRANCHE = "  ├─ "
"""Rattache une ligne à la sous-étape ouverte au-dessus."""

DERNIERE_BRANCHE = "  └─ "
"""Ferme la sous-étape : rattache sa dernière ligne."""

SUITE_DE_BRANCHE = "  │  "
"""Rattache une ligne à la branche ouverte au-dessus, le trait vertical se prolongeant."""


_LARGEUR_SOURCE = max(len(libelle) for libelle in SOURCE_LABELS.values())
"""Colonne des noms de source, à la largeur du plus long."""


_LARGEUR_PORTEE = len("2023-2026")
"""Colonne du périmètre d'une source, à la largeur d'une plage d'années."""


def branche_de_source(source: str, portee: str | None = None) -> str:
    """Libellé de la barre d'avancement d'une source : sa branche, son nom, et le remplissage qui aligne les barres d'une même phase les unes sous les autres.

    `portee` ajoute une colonne pour le périmètre en cours, une année par exemple. Une portée vide garde la colonne, pour aligner une source sans périmètre sur les autres.
    """
    libelle = f"{BRANCHE}{source_label(source):<{_LARGEUR_SOURCE}}"
    if portee is None:
        return libelle
    return f"{libelle} {portee:<{_LARGEUR_PORTEE}}"


def etape(logger: ScopedOrPlainLogger, titre: str, *args: object) -> None:
    """Ouvre une sous-étape : une ligne vide la détache de ce qui précède, puis son titre.

    `args` complète les champs de `titre`, comme pour tout message de journal.
    """
    ligne = f"{ETAPE}{titre}"
    logger.info("")
    logger.info(ligne, *args)


def forme(n: int, singulier: str, pluriel: str | None = None) -> str:
    """Rend « préfixe » ou « préfixes » selon `n`. Zéro prend le singulier, comme le veut le français.

    `pluriel` couvre les formes que le `s` final ne donne pas.
    """
    if pluriel is None:
        pluriel = f"{singulier}s"
    return singulier if abs(n) <= 1 else pluriel


def accord(n: int, singulier: str, pluriel: str | None = None) -> str:
    """Rend « 1 préfixe » ou « 3 préfixes »."""
    return f"{n} {forme(n, singulier, pluriel)}"


__all__ = [
    "BRANCHE",
    "DERNIERE_BRANCHE",
    "ETAPE",
    "SUITE_DE_BRANCHE",
    "accord",
    "branche_de_source",
    "etape",
    "forme",
]
