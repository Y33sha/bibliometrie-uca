"""Formatage des messages de journal : quantités accordées, sous-étapes d'une phase."""

from __future__ import annotations

from application.pipeline.logging_scope import ScopedOrPlainLogger

ETAPE = "▶ "
"""Ouvre une sous-étape d'une phase."""

BRANCHE = "  ├─ "
"""Rattache une ligne à la sous-étape ouverte au-dessus."""

DERNIERE_BRANCHE = "  └─ "
"""Ferme la sous-étape : rattache sa dernière ligne."""


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


__all__ = ["BRANCHE", "DERNIERE_BRANCHE", "ETAPE", "accord", "etape", "forme"]
