"""Helpers de normalisation de dates."""

from datetime import datetime


def french_date_to_iso(s: str | None) -> str | None:
    """Convertit ``"JJ/MM/AAAA"`` en ``"YYYY-MM-DD"``.

    Renvoie None si l'entrée est vide ou malformée. Valide les composants
    via ``datetime.strptime`` (rejette ``32/01/2023``, ``29/02/2023``
    non bissextile, etc.).
    """
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date().isoformat()
    except ValueError:
        return None
