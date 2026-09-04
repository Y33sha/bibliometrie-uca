"""Lecture d'un relevé SQL à une seule valeur.

Une requête écrite en texte ne porte pas le type de ses colonnes : `scalar_one` rend une valeur dont le vérificateur de types ne sait rien, et la déclaration de retour de l'appelant l'affirme sans que rien ne l'établisse. Ces fonctions font le contrôle, une fois, à l'endroit où la valeur passe du SQL au Python.

Elles s'appliquent aux relevés d'une ligne et d'une colonne — un `COUNT`, un identifiant rendu par `RETURNING`, un agrégat. Une valeur d'une autre nature que celle attendue signale une requête qui ne dit pas ce que son appelant croit, et lève.
"""

from datetime import datetime

from sqlalchemy import Result


def row_int(value: object) -> int:
    """L'entier porté par une valeur lue en base.

    Un booléen est écarté : Python le tient pour un entier, mais `true` reçu là où un compte ou un identifiant est attendu ne vaut pas 1.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"entier attendu du relevé, {type(value).__name__} reçu")
    return value


def scalar_int(result: Result[tuple[object, ...]]) -> int:
    """L'entier unique du relevé."""
    return row_int(result.scalar_one())


def scalar_datetime_or_none(result: Result[tuple[object, ...]]) -> datetime | None:
    """L'instant unique du relevé, ou `None` — le cas d'un agrégat sur un ensemble vide."""
    value = result.scalar_one()
    if value is None or isinstance(value, datetime):
        return value
    raise TypeError(f"instant attendu du relevé, {type(value).__name__} reçu")
