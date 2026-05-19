"""Lecture de la configuration applicative.

Lit depuis la table `config` en base. Les scripts du pipeline appellent ce module pour les paramètres externalisés (années, collections, affiliations, clés API, credentials ScanR).
"""

import datetime
import logging

from sqlalchemy import Connection, text

from domain.json_types import JsonValue

logger = logging.getLogger(__name__)


def _get_from_db(conn: Connection, key: str) -> JsonValue:
    """Lit une valeur depuis la table config. Retourne None si absente.

    Le retour est typé `JsonValue` (frontière JSONB libre) — chaque caller
    fait son `isinstance(...)` pour contraindre le type (str, list, dict, …)
    avant usage.
    """
    try:
        row = conn.execute(
            text("SELECT value FROM config WHERE key = :key"), {"key": key}
        ).one_or_none()
        return row.value if row else None
    except Exception:
        return None


def get_years(conn: Connection, mode: str = "full") -> list[int]:
    """Retourne la liste des années à extraire selon le mode.

    Lit pipeline_years_full ou pipeline_years_weekly depuis la table config
    (offset en nombre d'années depuis l'année courante).
    """
    key = "pipeline_years_weekly" if mode == "weekly" else "pipeline_years_full"
    offset = _get_from_db(conn, key)
    current_year = datetime.date.today().year

    if isinstance(offset, (int, str, float)) and not isinstance(offset, bool):
        try:
            n = int(offset)
            return list(range(current_year - n, current_year + 1))
        except (ValueError, TypeError):
            logger.warning(f"Valeur invalide pour {key}: {offset}")
    elif offset is not None:
        logger.warning(f"Valeur invalide pour {key}: {offset}")

    return [current_year]


def get_hal_collections(conn: Connection) -> dict[str, str]:
    """Retourne les collections HAL {code_hal: label}.

    Dérivé des structures du périmètre UCA qui ont un hal_collection renseigné,
    avec fallback sur la clé `hal_collections` de la table config.
    """
    try:
        from infrastructure.queries.perimeter import get_perimeter_structure_ids

        raw_perim = _get_from_db(conn, "perimeter_extraction")
        perim_code = raw_perim if isinstance(raw_perim, str) and raw_perim else "uca_wide"
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


def get_hal_extra_collections(conn: Connection) -> list[str]:
    """Retourne les collections HAL supplémentaires (hors structures du périmètre)."""
    val = _get_from_db(conn, "hal_extra_collections")
    if val and isinstance(val, list):
        return val
    return []


def get_openalex_api_key(conn: Connection) -> str | None:
    """Retourne la clé API OpenAlex (None si non configurée)."""
    val = _get_from_db(conn, "openalex_api_key")
    if val and isinstance(val, str):
        return val
    return None


_API_BASE_URLS_DEFAULTS: dict[str, str] = {
    # Extracteurs principaux (un endpoint par source)
    "hal": "https://api.archives-ouvertes.fr/search/",
    "openalex": "https://api.openalex.org/works",
    "wos": "https://api.clarivate.com/api/wos",
    "scanr": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
    "theses": "https://theses.fr/api/v1/theses/recherche/",
    # CrossRef : racine sans /works, l'adapter compose le chemin selon
    # l'usage (/works/<doi>, /works?filter=orcid:...)
    "crossref": "https://api.crossref.org",
    # Endpoints secondaires
    "openalex_sources": "https://api.openalex.org/sources",
    "unpaywall": "https://api.unpaywall.org/v2",
    "zenodo": "https://zenodo.org/api/records",
}


def get_api_base_urls(conn: Connection) -> dict[str, str]:
    """Retourne les URLs de base des API (extracteurs + endpoints secondaires).

    Les valeurs définies dans la table `config` écrasent les defaults ;
    les clés non configurées retombent sur les defaults, pour qu'un
    nouvel endpoint ajouté en code ne force pas à re-seeder la config.
    """
    val = _get_from_db(conn, "api_base_urls")
    if val and isinstance(val, dict):
        return {**_API_BASE_URLS_DEFAULTS, **val}
    return dict(_API_BASE_URLS_DEFAULTS)


def get_extraction_api_ids(conn: Connection, source: str) -> list[str]:
    """Retourne les identifiants API pour une source, déduits du périmètre d'extraction.

    Lit `perimeter_extraction` → structures du périmètre → `structures.api_ids[source]`.
    Seul circuit autorisé : pas de fallback vers d'anciennes clés `config.*` plates.
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
                # Tolérance scalaire historique (cf. `StructureApiIds._ensure_list`).
                result.append(ids)
        return list(dict.fromkeys(result))  # dédupliqué, ordre préservé
    except Exception as e:
        logger.warning(f"Impossible de dériver api_ids depuis le périmètre : {e}")
        return []


def get_openalex_email(conn: Connection) -> str:
    """Retourne l'email pour le polite pool OpenAlex (et fallback Crossref / Unpaywall).

    Raise si la row `openalex_email` n'est pas configurée : un email
    invalide envoyé à l'API peut entraîner un blacklist côté serveur,
    donc on force la config explicite plutôt que de fallback sur un
    email inventé.
    """
    val = _get_from_db(conn, "openalex_email")
    if val and isinstance(val, str):
        return val
    raise RuntimeError(
        "openalex_email manquant dans la table `config` — requis pour le polite pool "
        "des APIs (OpenAlex, Crossref, Unpaywall, etc.)."
    )


def get_crossref_email(conn: Connection) -> str:
    """Retourne l'email pour le polite pool CrossRef (envoyé via User-Agent)."""
    val = _get_from_db(conn, "crossref_email")
    if val and isinstance(val, str):
        return val
    # Fallback partagé avec OpenAlex si la clé dédiée n'est pas configurée.
    return get_openalex_email(conn)


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
