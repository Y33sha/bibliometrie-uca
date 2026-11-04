"""Lecture des réglages numériques du pipeline : années couvertes, plafonds et délais d'interrogation.

La table `config` contient ces réglages, modifiables dans l'interface d'administration.
"""

from sqlalchemy import Connection, text

from domain.config import ConfigKey, start_year_value
from domain.dates import today


def _stored_int(conn: Connection, key: ConfigKey) -> int | None:
    """Renvoie la valeur entière de `key` dans la table `config`, ou `None` si elle est vide. La table impose à ces clés un nombre entier."""
    value = conn.execute(
        text("SELECT value FROM config WHERE key = :key"), {"key": key.value}
    ).scalar_one()
    return None if value is None else int(value)


def cap(conn: Connection, key: ConfigKey) -> int | None:
    """Renvoie le plafond d'interrogations de `key`, ou `None` sans plafond : zéro vaut illimité."""
    return _stored_int(conn, key) or None


def delay(conn: Connection, key: ConfigKey) -> int:
    """Renvoie le délai de réinterrogation de `key`, en jours."""
    value = _stored_int(conn, key)
    assert value is not None, key
    return value


def fixed_start_year(conn: Connection) -> int | None:
    """Renvoie la première année moissonnée fixée en configuration, ou `None` si aucune année n'est fixée."""
    return _stored_int(conn, ConfigKey.PIPELINE_START_YEAR_FULL)


type YearRange = tuple[int, int]
"""Première et dernière années d'un run, incluses."""


def get_years(conn: Connection) -> list[int]:
    """Renvoie les années moissonnées par défaut, de la première année configurée (`start_year_value`) à l'année courante. Si la première année est future, seule l'année courante est renvoyée."""
    current_year = today().year
    start_year = start_year_value(fixed_start_year(conn), current_year)
    if start_year <= current_year:
        return list(range(start_year, current_year + 1))
    return [current_year]


def window_years(conn: Connection, years: YearRange | None) -> list[int]:
    """Renvoie les années de la fenêtre du run : celles de `years` (`--years`), sinon les années par défaut (`get_years`)."""
    if years is None:
        return get_years(conn)
    first, last = years
    return list(range(first, last + 1))
