"""Jour courant et conversions entre formes française et ISO des dates."""

from datetime import UTC, date, datetime


def today() -> date:
    """Renvoie le jour civil courant, en UTC."""
    return datetime.now(UTC).date()


def date_to_french(d: date) -> str:
    """Renvoie la date au format `JJ/MM/AAAA`."""
    return d.strftime("%d/%m/%Y")


def french_date_to_iso(s: str | None) -> str | None:
    """Convertit une date `JJ/MM/AAAA` au format ISO `AAAA-MM-JJ` ; `None` pour une entrée vide ou une date invalide."""
    if not s:
        return None
    try:
        # Une date sans heure : le fuseau n'entre pas dans sa lecture.
        return datetime.strptime(s.strip(), "%d/%m/%Y").date().isoformat()  # noqa: DTZ007
    except ValueError:
        return None
