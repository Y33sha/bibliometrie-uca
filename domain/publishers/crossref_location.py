"""Parsing du champ `location` de l'API Crossref Members.

Le champ est en texte libre, généralement `"City, State, Country"` ou `"City, Country"` (ex. `"Amsterdam, NX, Netherlands"`). Le dernier segment après la virgule est le nom du pays, résolu ensuite en ISO-2 via `place_name_forms`. Une location sans pays (`"Yerevan, AM"`) ressort `unmapped` — son segment final n'existe pas dans `place_name_forms`.
"""


def parse_country_segment(location: str) -> str | None:
    """Retourne le dernier segment d'une location Crossref.

    >>> parse_country_segment("Amsterdam, NX, Netherlands")
    'Netherlands'
    >>> parse_country_segment("Oxford, Oxfordshire, United Kingdom")
    'United Kingdom'
    >>> parse_country_segment("")
    >>> parse_country_segment("  ")
    """
    parts = [p.strip() for p in location.split(",") if p.strip()]
    return parts[-1] if parts else None
