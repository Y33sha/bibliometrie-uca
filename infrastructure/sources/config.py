"""Lecture de la configuration applicative.

Lit depuis la table `config` en base. Les scripts du pipeline appellent ce module pour les paramètres externalisés (années, collections, affiliations, clés API, credentials ScanR).
"""

import datetime
import logging

from sqlalchemy import Connection, text

from domain.types import JsonValue

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
    except Exception:
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
        logger.warning(f"Valeur invalide pour {key}: {value}")
    return None


def get_years(conn: Connection, start_year: int | None = None) -> list[int]:
    """Retourne les années à extraire : `[start_year … année courante]`.

    `start_year` est l'ancre absolue du range. Si `None`, on lit la config `pipeline_start_year_full`. Rétention cumulative. Fallback `[année courante]` si l'ancre est absente, invalide ou dans le futur.
    """
    current_year = datetime.date.today().year
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
        from infrastructure.queries.perimeter import get_perimeter_structure_ids

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
    except Exception as e:
        logger.warning(f"Impossible de dériver les collections HAL depuis le périmètre : {e}")

    val = _get_from_db(conn, "hal_collections")
    if val and isinstance(val, dict):
        return val

    return {}


def get_openalex_api_key(conn: Connection) -> str | None:
    """Retourne la clé API OpenAlex (None si non configurée)."""
    val = _get_from_db(conn, "openalex_api_key")
    if val and isinstance(val, str):
        return val
    return None


_API_BASE_URLS: dict[str, str] = {
    # Extracteurs principaux (un endpoint par source)
    "hal": "https://api.archives-ouvertes.fr/search/",
    "openalex": "https://api.openalex.org/works",
    "wos": "https://api.clarivate.com/api/wos",
    "scanr": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
    "theses": "https://theses.fr/api/v1/theses/recherche/",
    # CrossRef : racine sans /works, l'adapter compose le chemin selon
    # l'usage (/works/<doi>, /works?filter=orcid:...)
    "crossref": "https://api.crossref.org",
    # DataCite : racine, l'adapter compose `/dois` (query batch) ou `/dois/<doi>`.
    "datacite": "https://api.datacite.org",
    # Endpoints secondaires
    "openalex_sources": "https://api.openalex.org/sources",
    "openalex_publishers": "https://api.openalex.org/publishers",
    "unpaywall": "https://api.unpaywall.org/v2",
    "zenodo": "https://zenodo.org/api/records",
    "ror": "https://api.ror.org/v2/organizations",
    # DOAJ : racine de l'API, l'adapter compose `/search/journals/issn:{issn}`.
    "doaj": "https://doaj.org/api",
}


def get_api_base_urls() -> dict[str, str]:
    """URLs de base des API, par source (extracteurs + endpoints secondaires)."""
    return dict(_API_BASE_URLS)


def get_extraction_api_ids(conn: Connection, source: str) -> list[str]:
    """Retourne les identifiants API pour une source, déduits du périmètre d'extraction.

    Lit `perimeter_extraction` → structures du périmètre → `structures.api_ids[source]`.
    """
    perim_code = _get_from_db(conn, "perimeter_extraction")
    if not (perim_code and isinstance(perim_code, str)):
        return []
    try:
        from infrastructure.queries.perimeter import get_perimeter_structure_ids

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
    except Exception as e:
        logger.warning(f"Impossible de dériver api_ids depuis le périmètre : {e}")
        return []


def get_polite_pool_email_optional(conn: Connection) -> str | None:
    """Retourne l'email polite pool, ou `None` si non configuré (sans lever).

    Pour les consommateurs qui traitent l'email comme facultatif : OpenAlex, dont l'accès au polite pool peut aussi passer par une clé API. Les consommateurs qui exigent l'email utilisent `get_polite_pool_email`.
    """
    val = _get_from_db(conn, "polite_pool_email")
    if val and isinstance(val, str):
        return val
    return None


def get_polite_pool_email(conn: Connection) -> str:
    """Retourne l'email envoyé en polite pool aux APIs externes (Crossref, DataCite, Unpaywall, …).

    Raise si la row `polite_pool_email` n'est pas configurée : un email invalide envoyé à l'API peut entraîner un blacklist côté serveur, donc on force la config explicite plutôt que de fallback sur un email inventé.
    """
    email = get_polite_pool_email_optional(conn)
    if email is not None:
        return email
    raise RuntimeError(
        "polite_pool_email manquant dans la table `config` — requis pour le polite pool "
        "des APIs (Crossref, DataCite, Unpaywall, etc.)."
    )


def get_wos_api_key(conn: Connection) -> str:
    """Retourne la clé API WoS."""
    val = _get_from_db(conn, "wos_api_key")
    if val and isinstance(val, str):
        return val
    return ""


def get_scanr_credentials(conn: Connection) -> tuple[str, str]:
    """Retourne (username, password) pour l'API ScanR."""
    user = _get_from_db(conn, "scanr_username")
    pwd = _get_from_db(conn, "scanr_password")
    if isinstance(user, str) and isinstance(pwd, str) and user and pwd:
        return user, pwd
    return "", ""


def source_credentials_missing(conn: Connection, source: str) -> str | None:
    """Motif d'absence des credentials d'API d'une source, ou `None` si utilisable.

    Source unique de vérité de la présence des credentials par source, consultée par toutes les phases qui interrogent une API tierce (extraction, cross-import, refresh stale, enrichissements) : un accès dont cette fonction renvoie un motif est sauté proprement. HAL, theses.fr, DOI.org et DOAJ sont des API publiques sans credential (jamais de motif). L'email polite pool est traité comme un credential : Crossref, DataCite et Unpaywall en dépendent, et OpenAlex l'accepte à défaut de clé API. Le périmètre d'interrogation (collections, identifiants de structure, PPN) est un contrôle distinct, propre à l'extraction bulk.
    """
    if source in ("hal", "theses"):
        return None
    if source == "openalex":
        if get_openalex_api_key(conn) or get_polite_pool_email_optional(conn):
            return None
        return (
            "ni clé API ni email polite pool (config.openalex_api_key / config.polite_pool_email)"
        )
    if source == "wos":
        return None if get_wos_api_key(conn) else "clé API absente (config.wos_api_key)"
    if source == "scanr":
        user, password = get_scanr_credentials(conn)
        if user and password:
            return None
        return "credentials absents (config.scanr_username / config.scanr_password)"
    if source in ("crossref", "datacite", "unpaywall"):
        if get_polite_pool_email_optional(conn):
            return None
        return "email polite pool absent (config.polite_pool_email)"
    return None
