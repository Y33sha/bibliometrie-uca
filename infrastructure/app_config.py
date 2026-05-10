"""Lecture de la configuration applicative.

Lit depuis la table `config` en base. Les scripts du pipeline appellent ce
module pour les paramètres externalisés (années, collections, affiliations,
clés API, credentials ScanR).

Les fonctions acceptent indifféremment un curseur psycopg (mode legacy
des CLI non migrés) ou une `Connection` SA (mode cible). Le dispatch
disparaît quand tous les CLI pipeline sont migrés en SA.
"""

import datetime
import logging
from typing import Any

from sqlalchemy import Connection, text

logger = logging.getLogger(__name__)


def _get_from_db(conn_or_cur: Any, key: Any) -> Any:
    """Lit une valeur depuis la table config. Retourne None si absente."""
    try:
        if isinstance(conn_or_cur, Connection):
            row = conn_or_cur.execute(
                text("SELECT value FROM config WHERE key = :key"), {"key": key}
            ).one_or_none()
            return row.value if row else None
        conn_or_cur.execute("SELECT value FROM config WHERE key = %s", (key,))
        row = conn_or_cur.fetchone()
        if row:
            return row[0] if isinstance(row, tuple) else row["value"]
    except Exception:
        pass
    return None


def get_years(cur: Any, mode: str = "full") -> list[int]:
    """Retourne la liste des années à extraire selon le mode.

    Lit pipeline_years_full ou pipeline_years_weekly depuis la table config
    (offset en nombre d'années depuis l'année courante).
    """
    key = "pipeline_years_weekly" if mode == "weekly" else "pipeline_years_full"
    offset = _get_from_db(cur, key)
    current_year = datetime.date.today().year

    if offset is not None:
        try:
            n = int(offset) if not isinstance(offset, int) else offset
            return list(range(current_year - n, current_year + 1))
        except (ValueError, TypeError):
            logger.warning(f"Valeur invalide pour {key}: {offset}")

    return [current_year]


def get_hal_collections(conn_or_cur: Any) -> dict[str, str]:
    """Retourne les collections HAL {code_hal: label}.

    Dérivé des structures du périmètre UCA qui ont un hal_collection renseigné,
    avec fallback sur la clé `hal_collections` de la table config.
    """
    # 1. Depuis les structures du périmètre d'extraction
    try:
        from infrastructure.perimeter import get_perimeter_structure_ids

        perim_code = _get_from_db(conn_or_cur, "perimeter_extraction") or "uca_wide"
        perimeter_ids = get_perimeter_structure_ids(conn_or_cur, perim_code)
        if perimeter_ids:
            if isinstance(conn_or_cur, Connection):
                rows = conn_or_cur.execute(
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
            else:
                conn_or_cur.execute(
                    """
                    SELECT hal_collection, COALESCE(acronym, name) AS label
                    FROM structures
                    WHERE id = ANY(%s) AND hal_collection IS NOT NULL AND hal_collection != ''
                """,
                    (list(perimeter_ids),),
                )
                rows = conn_or_cur.fetchall()
                if rows:
                    return {
                        (r["hal_collection"] if isinstance(r, dict) else r[0]): (
                            r["label"] if isinstance(r, dict) else r[1]
                        )
                        for r in rows
                    }
    except Exception as e:
        logger.warning(f"Impossible de dériver les collections HAL depuis le périmètre : {e}")

    # 2. Fallback config DB
    val = _get_from_db(conn_or_cur, "hal_collections")
    if val and isinstance(val, dict):
        return val

    return {}


def get_hal_extra_collections(cur: Any) -> list[str]:
    """Retourne les collections HAL supplémentaires (hors structures du périmètre)."""
    val = _get_from_db(cur, "hal_extra_collections")
    if val and isinstance(val, list):
        return val
    return []


def get_openalex_api_key(cur: Any) -> str | None:
    """Retourne la clé API OpenAlex (None si non configurée)."""
    val = _get_from_db(cur, "openalex_api_key")
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


def get_api_base_urls(cur: Any) -> dict[str, str]:
    """Retourne les URLs de base des API (extracteurs + endpoints secondaires).

    Les valeurs définies dans la table `config` écrasent les defaults ;
    les clés non configurées retombent sur les defaults, pour qu'un
    nouvel endpoint ajouté en code ne force pas à re-seeder la config.
    """
    val = _get_from_db(cur, "api_base_urls")
    if val and isinstance(val, dict):
        return {**_API_BASE_URLS_DEFAULTS, **val}
    return dict(_API_BASE_URLS_DEFAULTS)


def get_extraction_api_ids(conn_or_cur: Any, source: str) -> list[str]:
    """Retourne les identifiants API pour une source, déduits du périmètre d'extraction.

    Lit perimeter_extraction → structures du périmètre → api_ids[source].
    Fallback sur les anciennes clés config (openalex_institution_ids, etc.).
    """
    # 1. Depuis les structures du périmètre
    perim_code = _get_from_db(conn_or_cur, "perimeter_extraction")
    if perim_code and isinstance(perim_code, str):
        try:
            from infrastructure.perimeter import get_perimeter_structure_ids

            struct_ids = get_perimeter_structure_ids(conn_or_cur, perim_code)
            if struct_ids:
                if isinstance(conn_or_cur, Connection):
                    sa_rows = conn_or_cur.execute(
                        text(
                            "SELECT api_ids->:src AS ids FROM structures "
                            "WHERE id = ANY(:ids) AND api_ids ? :src"
                        ),
                        {"src": source, "ids": list(struct_ids)},
                    ).all()
                    raw_ids = [r.ids for r in sa_rows]
                else:
                    conn_or_cur.execute(
                        """
                        SELECT api_ids->%s AS ids
                        FROM structures
                        WHERE id = ANY(%s) AND api_ids ? %s
                    """,
                        (source, list(struct_ids), source),
                    )
                    raw_ids = [
                        (r["ids"] if isinstance(r, dict) else r[0]) for r in conn_or_cur.fetchall()
                    ]
                result: list[str] = []
                for ids in raw_ids:
                    if isinstance(ids, list):
                        result.extend(ids)
                    elif isinstance(ids, str):
                        result.append(ids)
                if result:
                    return list(dict.fromkeys(result))  # dédupliqué, ordre préservé
        except Exception as e:
            logger.warning(f"Impossible de dériver api_ids depuis le périmètre : {e}")

    # 2. Fallback anciennes clés config
    fallback_keys = {
        "openalex": "openalex_institution_ids",
        "wos": "wos_affiliations",
        "scanr": "scanr_affiliation_ids",
        "theses": "theses_etab_ppns",
    }
    fallback_key = fallback_keys.get(source)
    if fallback_key:
        val = _get_from_db(conn_or_cur, fallback_key)
        if val and isinstance(val, list):
            return val

    return []


def get_openalex_institution_ids(cur: Any) -> list[str]:
    """Retourne les IDs institution OpenAlex."""
    val = _get_from_db(cur, "openalex_institution_ids")
    if val and isinstance(val, list):
        return val
    return []


def get_wos_affiliations(cur: Any) -> list[str]:
    """Retourne les noms OG WoS."""
    val = _get_from_db(cur, "wos_affiliations")
    if val and isinstance(val, list):
        return val
    return []


def get_openalex_email(cur: Any) -> str:
    """Retourne l'email pour le polite pool OpenAlex."""
    val = _get_from_db(cur, "openalex_email")
    if val and isinstance(val, str):
        return val
    return "bibliometrie@uca.fr"


def get_crossref_email(cur: Any) -> str:
    """Retourne l'email pour le polite pool CrossRef (envoyé via User-Agent)."""
    val = _get_from_db(cur, "crossref_email")
    if val and isinstance(val, str):
        return val
    # Fallback partagé avec OpenAlex si la clé dédiée n'est pas configurée.
    return get_openalex_email(cur)


def get_wos_api_key(cur: Any) -> str:
    """Retourne la clé API WoS."""
    val = _get_from_db(cur, "wos_api_key")
    if val and isinstance(val, str):
        return val
    return ""


def get_scanr_affiliation_ids(cur: Any) -> list[str]:
    """Retourne les IDs SIREN des structures ScanR."""
    val = _get_from_db(cur, "scanr_affiliation_ids")
    if val and isinstance(val, list):
        return val
    return []


def get_theses_etab_ppns(cur: Any) -> list[str]:
    """Retourne les PPN IdRef des établissements de soutenance pour theses.fr."""
    val = _get_from_db(cur, "theses_etab_ppns")
    if val and isinstance(val, list):
        return val
    return []


def get_scanr_credentials(cur: Any) -> tuple[str, str]:
    """Retourne (username, password) pour l'API ScanR."""
    user = _get_from_db(cur, "scanr_username")
    pwd = _get_from_db(cur, "scanr_password")
    if user and pwd:
        return user, pwd
    return "", ""
