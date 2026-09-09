"""Formatage des quantités dans les messages de journal."""

from __future__ import annotations


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


__all__ = ["accord", "forme"]
