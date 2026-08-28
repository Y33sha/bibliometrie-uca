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
    """Retourne les collections HAL {code_hal: label}.

    Dérivé des structures du périmètre qui ont un hal_collection renseigné, avec fallback sur la clé `hal_collections` de la table config.
    """
    try:
        from infrastructure.read_models.perimeters import get_perimeter_structure_ids

        raw_perim = _get_from_db(conn, "perimeter_extraction")
        perim_code = raw_perim if isinstance(raw_perim, str) and raw_perim else "alliance_uca"
        perimeter_ids = get_perimeter_structure_ids(conn, perim_code)
        if perimeter_ids:
            rows = conn.execute(
                text(
                    "SELECT hal_collection, COALESCE(acronym, name) AS label "
                    "FROM structures "
                    "WHERE id = ANY(:ids) "
                    "AND hal_collection IS NOT NULL AND hal_collection != ''"
                ),
                {"ids": list(perimeter_ids)},
            ).all()
            if rows:
                return {r.hal_collection: r.label for r in rows}
    except SQLAlchemyError as e:
        logger.warning("Impossible de dériver les collections HAL depuis le périmètre : %s", e)

    val = _get_from_db(conn, "hal_collections")
    if val and isinstance(val, dict):
        return val

    return {}


def get_openalex_api_key() -> str | None:
    """Clé d'API OpenAlex, ou `None` si elle n'est pas configurée."""
    return settings.openalex_api_key.get_secret_value() or None


def get_extraction_api_ids(conn: Connection, source: str) -> list[str]:
    """Retourne les identifiants API pour une source, déduits du périmètre d'extraction.

    Lit `perimeter_extraction` → structures du périmètre → `structures.api_ids[source]`.
    """
    perim_code = _get_from_db(conn, "perimeter_extraction")
    if not (perim_code and isinstance(perim_code, str)):
        return []
    try:
        from infrastructure.read_models.perimeters import get_perimeter_structure_ids

        struct_ids = get_perimeter_structure_ids(conn, perim_code)
        if not struct_ids:
            return []
        rows = conn.execute(
            text(
                "SELECT api_ids->:src AS ids FROM structures "
                "WHERE id = ANY(:ids) AND api_ids ? :src"
            ),
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
    except SQLAlchemyError as e:
        logger.warning("Impossible de dériver api_ids depuis le périmètre : %s", e)
        return []


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
