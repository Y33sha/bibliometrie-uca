"""Lecture des réglages numériques du pipeline (`domain.config.ConfigKey`) : années couvertes, plafonds et délais d'interrogation.

Ces paramètres vivent dans la table `config` et se modifient depuis l'interface d'administration. Le périmètre d'extraction se lit dans `infrastructure/read_models/perimeters.py`, les identifiants d'accès aux sources dans `pipeline/ingestion/credentials.py`.
"""

import logging

from sqlalchemy import Connection, text

from domain.config import ConfigKey, cap_value, delay_value
from domain.dates import today

logger = logging.getLogger(__name__)


def _stored_int(conn: Connection, key: ConfigKey) -> int | None:
    """Valeur entière de `key` dans la table `config`, ou `None` si elle est absente ou illisible. Une valeur illisible est journalisée."""
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
    """Plafond d'interrogations de `key`, `None` valant illimité (`cap_value`)."""
    return cap_value(key, _stored_int(conn, key))


def delay(conn: Connection, key: ConfigKey) -> int:
    """Délai de réinterrogation de `key`, en jours (`delay_value`)."""
    return delay_value(key, _stored_int(conn, key))


def get_years(conn: Connection, start_year: int | None = None) -> list[int]:
    """Retourne les années à extraire : `[start_year … année courante]`.

    `start_year` est l'ancre absolue du range. Si `None`, on lit la config `pipeline_start_year_full`. Rétention cumulative. Fallback `[année courante]` si l'ancre est absente, invalide ou dans le futur.
    """
    current_year = today().year
    if start_year is None:
        start_year = _stored_int(conn, ConfigKey.PIPELINE_START_YEAR_FULL)
    if start_year is not None and start_year <= current_year:
        return list(range(start_year, current_year + 1))
    return [current_year]


def window_years(conn: Connection, *, start_year: int | None, year: int | None) -> list[int]:
    """Années de la fenêtre du run : `year` (`--year`), sinon `[start_year … année courante]` (`get_years`)."""
    return [year] if year else get_years(conn, start_year)
