"""Lecture des réglages numériques du pipeline (`domain.config.ConfigKey`) : années couvertes, plafonds et délais d'interrogation.

La table `config` contient ces réglages, modifiables dans l'interface d'administration.
"""

import logging

from sqlalchemy import Connection, text

from domain.config import ConfigKey, cap_value, delay_value
from domain.dates import today

logger = logging.getLogger(__name__)


def _stored_int(conn: Connection, key: ConfigKey) -> int | None:
    """Renvoie la valeur entière de `key` dans la table `config`, ou `None` si elle est absente ou illisible. Une valeur illisible est journalisée."""
    row = conn.execute(
        text("SELECT value FROM config WHERE key = :key"), {"key": key.value}
    ).one_or_none()
    value = row.value if row else None
    if isinstance(value, (int, str, float)) and not isinstance(value, bool):
        try:
            return int(value)
        except ValueError, TypeError:
            pass
    if value is not None:
        logger.warning("Valeur invalide pour %s: %s", key, value)
    return None


def cap(conn: Connection, key: ConfigKey) -> int | None:
    """Renvoie le plafond d'interrogations de `key`, ou `None` sans plafond (`cap_value`)."""
    return cap_value(key, _stored_int(conn, key))


def delay(conn: Connection, key: ConfigKey) -> int:
    """Renvoie le délai de réinterrogation de `key`, en jours (`delay_value`)."""
    return delay_value(key, _stored_int(conn, key))


def get_years(conn: Connection, start_year: int | None = None) -> list[int]:
    """Renvoie les années à moissonner, de `start_year` à l'année courante.

    Sans `start_year`, la clé `pipeline_start_year_full` donne la première année. Si la première année manque ou est future, seule l'année courante est renvoyée.
    """
    current_year = today().year
    if start_year is None:
        start_year = _stored_int(conn, ConfigKey.PIPELINE_START_YEAR_FULL)
    if start_year is not None and start_year <= current_year:
        return list(range(start_year, current_year + 1))
    return [current_year]


def window_years(conn: Connection, *, start_year: int | None, year: int | None) -> list[int]:
    """Renvoie les années de la fenêtre du run : `year` (`--year`), sinon de `start_year` à l'année courante (`get_years`)."""
    return [year] if year else get_years(conn, start_year)
