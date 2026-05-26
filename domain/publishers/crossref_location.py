"""Parsing du champ `location` retourné par l'API Crossref Members.

Le champ est en texte libre, généralement `"City, State, Country"` ou
`"City, Country"` (ex. `"Amsterdam, NX, Netherlands"`, `"Oxford,
Oxfordshire, United Kingdom"`). Le dernier segment après la virgule
est le nom du pays — qui doit ensuite être résolu en ISO-2 via la
table `country_name_forms` (côté infra / application).

Cas dégénérés observés (audit `audit_crossref_member_countries`) :
location qui ne contient que ville + état/région sans pays
("Yerevan, AM"). Ces cas ressortiront comme `unmapped` côté pipeline
car le segment final n'existera pas dans `country_name_forms`.
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
