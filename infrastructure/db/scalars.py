"""Lecture d'un relevé SQL à une seule valeur.

Une requête écrite en texte ignore le type de ses colonnes. La valeur renvoyée par `scalar_one` est donc inconnue du vérificateur de types. Ces fonctions contrôlent le type au passage du SQL au Python.

Elles s'appliquent aux relevés d'une ligne et d'une colonne : un `COUNT`, un identifiant renvoyé par `RETURNING`, un agrégat. Une valeur d'un autre type que le type attendu lève `TypeError`.
"""

from datetime import datetime
from typing import Protocol


class ScalarResult(Protocol):
    """Relevé à valeur unique."""

    def scalar_one(self) -> object: ...


def row_int(value: object) -> int:
    """Renvoie une valeur lue en base, après contrôle de son type entier.

    Un booléen est refusé. Python le tient pour un entier, mais `true` à la place d'un compte ou d'un identifiant est une erreur.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"entier attendu du relevé, {type(value).__name__} reçu")
    return value


def scalar_int(result: ScalarResult) -> int:
    """Renvoie l'entier unique du relevé."""
    return row_int(result.scalar_one())


def scalar_datetime_or_none(result: ScalarResult) -> datetime | None:
    """Renvoie l'instant unique du relevé, ou `None` pour un agrégat sur un ensemble vide."""
    value = result.scalar_one()
    if value is None or isinstance(value, datetime):
        return value
    raise TypeError(f"instant attendu du relevé, {type(value).__name__} reçu")
