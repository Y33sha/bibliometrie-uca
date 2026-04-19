"""Parsers pour les query params HTTP (CSV → listes typées).

Les constructeurs de filtres SQL (apply_*_filter, PUB_IS_UCA, etc.) ont
migré dans `infrastructure/db/queries/filters.py` — ils construisent du
SQL, donc appartiennent à l'infrastructure. Importer depuis là.
"""


def parse_int_csv(s: str) -> list[int]:
    """Parse une chaîne CSV d'entiers (ex: '1,2,3')."""
    return [int(v) for v in s.split(",") if v.strip()] if s else []


def parse_str_csv(s: str) -> list[str]:
    """Parse une chaîne CSV de strings."""
    return [v.strip() for v in s.split(",") if v.strip()] if s else []
