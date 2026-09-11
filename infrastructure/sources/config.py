"""Lecture de la configuration du pipeline.

Deux origines, selon la nature du réglage. Les paramètres d'exploitation — années couvertes, périmètre d'extraction, collections HAL, identifiants de structure par source — vivent dans la table `config` et se modifient depuis l'interface d'administration. Les identifiants d'accès aux sources externes, eux, sont des secrets : ils viennent de l'environnement du processus, comme les autres secrets de l'application.
"""

import logging

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from domain.dates import today
from domain.types import JsonValue
from infrastructure.settings import settings

logger = logging.getLogger(__name__)

UNPAYWALL_MAX_PER_RUN_DEFAULT = 10_000
"""Plafond retenu quand la configuration ne porte pas `unpaywall_max_per_run`."""


def _get_from_db(conn: Connection, key: str) -> JsonValue:
    """Lit une valeur depuis la table config. Retourne None si absente.

    Le retour est typé `JsonValue` (frontière JSONB libre) — chaque caller fait son `isinstance(...)` pour contraindre le type (str, list, dict, …) avant usage.
    """
    try:
        row = conn.execute(
            text("SELECT value FROM config WHERE key = :key"), {"key": key}
        ).one_or_none()
        return row.value if row else None
    except SQLAlchemyError:
        return None


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
    """Nombre maximum de DOI interrogés par source cible au cross-import, `None` valant illimité.

    Le plafond vaut pour chaque source prise séparément : les quotas sont propres à chaque API.
    """
    return _plafond(conn, "fetch_missing_max_per_source", None)


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


def get_hal_collections(conn: Connection) -> dict[str, str]:
    """Collections HAL {code_hal: label} des structures du périmètre d'extraction qui en portent une."""
    from infrastructure.read_models.perimeters import get_extraction_structure_ids

    structure_ids = get_extraction_structure_ids(conn)
    if not structure_ids:
        return {}
    rows = conn.execute(
        text(
            "SELECT hal_collection, COALESCE(acronym, name) AS label "
            "FROM structures "
            "WHERE id = ANY(:ids) "
            "AND hal_collection IS NOT NULL AND hal_collection != ''"
        ),
        {"ids": list(structure_ids)},
    ).all()
    return {r.hal_collection: r.label for r in rows}


def get_openalex_api_key() -> str | None:
    """Clé d'API OpenAlex, ou `None` si elle n'est pas configurée."""
    return settings.openalex_api_key.get_secret_value() or None


def get_extraction_api_ids(conn: Connection, source: str) -> list[str]:
    """Retourne les identifiants API pour une source, déduits du périmètre d'extraction.

    Lit `perimeter_extraction` → structures du périmètre → `structures.api_ids[source]`.
    """
    from infrastructure.read_models.perimeters import get_extraction_structure_ids

    struct_ids = get_extraction_structure_ids(conn)
    if not struct_ids:
        return []
    rows = conn.execute(
        text("SELECT api_ids->:src AS ids FROM structures WHERE id = ANY(:ids) AND api_ids ? :src"),
        {"src": source, "ids": list(struct_ids)},
    ).all()
    result: list[str] = []
    for row in rows:
        ids = row.ids
        if isinstance(ids, list):
            result.extend(ids)
        elif isinstance(ids, str):
            # Tolérance d'un scalaire (cf. `StructureApiIds._ensure_list`).
            result.append(ids)
    return list(dict.fromkeys(result))  # dédupliqué, ordre préservé


def get_polite_pool_email_optional() -> str | None:
    """Adresse annoncée en polite pool, ou `None` si elle n'est pas configurée (sans lever).

    Pour les consommateurs qui la traitent comme facultative : OpenAlex, dont l'accès au polite pool peut aussi passer par une clé d'API. Ceux qui l'exigent utilisent `get_polite_pool_email`.
    """
    return settings.polite_pool_email or None


def get_polite_pool_email() -> str:
    """Adresse annoncée en polite pool aux API externes (Crossref, DataCite, Unpaywall, …).

    Lève si elle n'est pas configurée. Une adresse inventée expose à un blocage côté serveur.
    """
    email = get_polite_pool_email_optional()
    if email is not None:
        return email
    raise RuntimeError(
        "POLITE_POOL_EMAIL manquant dans l'environnement — requis pour le polite pool "
        "des API (Crossref, DataCite, Unpaywall, etc.)."
    )


def get_wos_api_key() -> str:
    """Clé d'API Web of Science, chaîne vide si elle n'est pas configurée."""
    return settings.wos_api_key.get_secret_value()


def get_scanr_credentials() -> tuple[str, str]:
    """Identifiants de l'API ScanR, `("", "")` si l'un des deux manque."""
    user, password = settings.scanr_username, settings.scanr_password.get_secret_value()
    if user and password:
        return user, password
    return "", ""


def source_credentials_missing(source: str) -> str | None:
    """Motif d'absence des credentials d'API d'une source, ou `None` si utilisable.

    Source unique de vérité de la présence des credentials par source, consultée par toutes les phases qui interrogent une API tierce (extraction, cross-import, refresh stale, enrichissements) : un accès dont cette fonction renvoie un motif est sauté proprement. HAL, theses.fr, DOI.org et DOAJ sont des API publiques sans credential (jamais de motif). L'adresse polite pool est traitée comme un identifiant : Crossref, DataCite et Unpaywall en dépendent, et OpenAlex l'accepte à défaut de clé d'API. Le périmètre d'interrogation (collections, identifiants de structure, PPN) est un contrôle distinct, propre à l'extraction bulk.
    """
    if source in ("hal", "theses"):
        return None
    if source == "openalex":
        if get_openalex_api_key() or get_polite_pool_email_optional():
            return None
        return "ni clé d'API ni adresse polite pool (OPENALEX_API_KEY / POLITE_POOL_EMAIL)"
    if source == "wos":
        return None if get_wos_api_key() else "clé d'API absente (WOS_API_KEY)"
    if source == "scanr":
        user, password = get_scanr_credentials()
        if user and password:
            return None
        return "identifiants absents (SCANR_USERNAME / SCANR_PASSWORD)"
    if source in ("crossref", "datacite", "unpaywall"):
        if get_polite_pool_email_optional():
            return None
        return "adresse polite pool absente (POLITE_POOL_EMAIL)"
    return None
