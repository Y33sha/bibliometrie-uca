"""Lecture des réglages numériques du pipeline : années couvertes, plafonds et délais d'interrogation.

La table `config` contient ces réglages, modifiables dans l'interface d'administration.
"""

from sqlalchemy import Connection, text

from domain.config import ConfigKey, cap_value, delay_value, start_year_value
from domain.dates import today


def _stored_int(conn: Connection, key: ConfigKey) -> int | None:
    """Renvoie la valeur entière de `key` dans la table `config`, ou `None` si la clé est absente ou vide. La table impose à ces clés un nombre entier."""
    value = conn.execute(
        text("SELECT value FROM config WHERE key = :key"), {"key": key.value}
    ).scalar_one_or_none()
    return None if value is None else int(value)


def cap(conn: Connection, key: ConfigKey) -> int | None:
    """Renvoie le plafond d'interrogations de `key`, ou `None` sans plafond (`cap_value`)."""
    return cap_value(key, _stored_int(conn, key))


def delay(conn: Connection, key: ConfigKey) -> int:
    """Renvoie le délai de réinterrogation de `key`, en jours (`delay_value`)."""
    return delay_value(key, _stored_int(conn, key))


def fixed_start_year(conn: Connection) -> int | None:
    """Renvoie la première année moissonnée fixée en configuration, ou `None` si aucune année n'est fixée."""
    return _stored_int(conn, ConfigKey.PIPELINE_START_YEAR_FULL)


def get_years(conn: Connection, start_year: int | None = None) -> list[int]:
    """Renvoie les années à moissonner, de `start_year` à l'année courante.

    Sans `start_year`, la première année vient de la configuration (`start_year_value`). Si la première année est future, seule l'année courante est renvoyée.
    """
    current_year = today().year
    if start_year is None:
        start_year = start_year_value(fixed_start_year(conn), current_year)
    if start_year <= current_year:
        return list(range(start_year, current_year + 1))
    return [current_year]


def window_years(conn: Connection, *, start_year: int | None, year: int | None) -> list[int]:
    """Renvoie les années de la fenêtre du run : `year` (`--year`), sinon de `start_year` à l'année courante (`get_years`)."""
    return [year] if year else get_years(conn, start_year)
