"""Lecture de la configuration d'exploitation du pipeline : années couvertes, plafonds et délais d'interrogation.

Ces paramètres vivent dans la table `config` et se modifient depuis l'interface d'administration. Le périmètre d'extraction se lit dans `infrastructure/read_models/perimeters.py`, les identifiants d'accès aux sources dans `pipeline/ingestion/credentials.py`.
"""

import logging

from sqlalchemy import Connection, text

from domain.dates import today
from domain.types import JsonValue

logger = logging.getLogger(__name__)

UNPAYWALL_MAX_PER_RUN_DEFAULT = 10_000
"""Plafond retenu quand la configuration ne porte pas `unpaywall_max_per_run`."""


def _get_from_db(conn: Connection, key: str) -> JsonValue:
    """Lit une valeur depuis la table config. Retourne None si absente.

    Le retour est typé `JsonValue` (frontière JSONB libre) — chaque caller fait son `isinstance(...)` pour contraindre le type (str, list, dict, …) avant usage.
    """
    row = conn.execute(
        text("SELECT value FROM config WHERE key = :key"), {"key": key}
    ).one_or_none()
    return row.value if row else None


def _config_int(conn: Connection, key: str) -> int | None:
    """Lit une valeur config et la contraint en `int`, ou `None` si absente/invalide."""
    value = _get_from_db(conn, key)
    if isinstance(value, (int, str, float)) and not isinstance(value, bool):
        try:
            return int(value)
        except (ValueError, TypeError):
            pass
    if value is not None:
        logger.warning("Valeur invalide pour %s: %s", key, value)
    return None


def _plafond(conn: Connection, key: str, defaut: int | None) -> int | None:
    """Plafond d'interrogations lu en configuration, `None` valant illimité.

    Zéro et les valeurs négatives valent illimité : l'interface d'administration expose un entier, et le champ vidé y revient à retirer la borne. `defaut` s'applique quand la clé est absente ou illisible.
    """
    valeur = _config_int(conn, key)
    if valeur is None:
        return defaut
    return valeur if valeur > 0 else None


def get_unpaywall_max_per_run(conn: Connection) -> int | None:
    """Nombre maximum de DOI vérifiés auprès d'Unpaywall par run, `None` valant illimité.

    Le plafond lisse la charge : le stock des jamais-vérifiés s'écoule sur plusieurs runs au lieu d'un pic.
    """
    return _plafond(conn, "unpaywall_max_per_run", UNPAYWALL_MAX_PER_RUN_DEFAULT)


def get_fetch_missing_max_per_source(conn: Connection) -> int | None:
    """Nombre maximum de DOI interrogés par source cible à la phase `fetch_missing`, `None` valant illimité.

    Le plafond vaut pour chaque source prise séparément : les quotas sont propres à chaque API.
    """
    return _plafond(conn, "fetch_missing_max_per_source", None)


FETCH_STALE_AFTER_DAYS_DEFAULT = 90
"""Délai retenu quand la configuration ne porte pas `fetch_stale_after_days`."""

FETCH_MISSING_RETRY_AFTER_DAYS_DEFAULT = 30
"""Délai retenu quand la configuration ne porte pas `fetch_missing_retry_after_days`."""

UNPAYWALL_RECHECK_AFTER_DAYS_DEFAULT = 15
"""Délai retenu quand la configuration ne porte pas `unpaywall_recheck_after_days`."""

DOAJ_REFRESH_AFTER_DAYS_DEFAULT = 30
"""Délai retenu quand la configuration ne porte pas `doaj_refresh_after_days`."""


def _delai(conn: Connection, key: str, defaut: int) -> int:
    """Délai de réinterrogation lu en configuration, en jours. `defaut` s'applique quand la clé est absente, illisible ou inférieure à un jour."""
    valeur = _config_int(conn, key)
    return valeur if valeur is not None and valeur >= 1 else defaut


def get_fetch_stale_after_days(conn: Connection) -> int:
    """Âge, en jours, au-delà duquel un document non revu est interrogé de nouveau à sa source."""
    return _delai(conn, "fetch_stale_after_days", FETCH_STALE_AFTER_DAYS_DEFAULT)


def get_fetch_missing_retry_after_days(conn: Connection) -> int:
    """Délai, en jours, avant de chercher de nouveau un identifiant introuvable dans une source."""
    return _delai(conn, "fetch_missing_retry_after_days", FETCH_MISSING_RETRY_AFTER_DAYS_DEFAULT)


def get_unpaywall_recheck_after_days(conn: Connection) -> int:
    """Délai, en jours, avant de vérifier de nouveau le statut open access d'une publication auprès d'Unpaywall."""
    return _delai(conn, "unpaywall_recheck_after_days", UNPAYWALL_RECHECK_AFTER_DAYS_DEFAULT)


def get_doaj_refresh_after_days(conn: Connection) -> int:
    """Délai, en jours, avant de télécharger de nouveau le fichier du DOAJ."""
    return _delai(conn, "doaj_refresh_after_days", DOAJ_REFRESH_AFTER_DAYS_DEFAULT)


def get_years(conn: Connection, start_year: int | None = None) -> list[int]:
    """Retourne les années à extraire : `[start_year … année courante]`.

    `start_year` est l'ancre absolue du range. Si `None`, on lit la config `pipeline_start_year_full`. Rétention cumulative. Fallback `[année courante]` si l'ancre est absente, invalide ou dans le futur.
    """
    current_year = today().year
    if start_year is None:
        start_year = _config_int(conn, "pipeline_start_year_full")
    if start_year is not None and start_year <= current_year:
        return list(range(start_year, current_year + 1))
    return [current_year]
