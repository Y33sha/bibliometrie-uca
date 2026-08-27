"""Helpers de normalisation de dates."""

from datetime import UTC, date, datetime


def today() -> date:
    """Jour civil courant, en temps universel coordonné."""
    return datetime.now(UTC).date()


def french_date_to_iso(s: str | None) -> str | None:
    """Convertit `"JJ/MM/AAAA"` en `"YYYY-MM-DD"`.

    Renvoie None si l'entrée est vide ou malformée. Valide les composants via `datetime.strptime` (rejette `32/01/2023`, `29/02/2023` non bissextile, etc.).
    """
    if not s:
        return None
    try:
        # Une date sans heure : le fuseau n'entre pas dans sa lecture.
        return datetime.strptime(s.strip(), "%d/%m/%Y").date().isoformat()  # noqa: DTZ007
    except ValueError:
        return None
