"""Lecture de la configuration applicative.

Lit depuis la table `config` en base. Les scripts du pipeline appellent ce
module pour les paramètres externalisés (années, collections, affiliations,
clés API, credentials ScanR).
"""

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_from_db(cur: Any, key: Any) -> Any:
    """Lit une valeur depuis la table config. Retourne None si absente."""
    try:
        cur.execute("SELECT value FROM config WHERE key = %s", (key,))
        row = cur.fetchone()
        if row:
            return row[0] if isinstance(row, tuple) else row["value"]
    except Exception:
        pass
    return None


async def _async_get_from_db(cur: Any, key: Any) -> Any:
    """Variante async de `_get_from_db` (§2.12)."""
    try:
        await cur.execute("SELECT value FROM config WHERE key = %s", (key,))
        row = await cur.fetchone()
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


def get_hal_collections(cur: Any) -> dict[str, str]:
    """Retourne les collections HAL {code_hal: label}.

    Dérivé des structures du périmètre UCA qui ont un hal_collection renseigné,
    avec fallback sur la clé `hal_collections` de la table config.
    """
    # 1. Depuis les structures du périmètre d'extraction
    try:
        from infrastructure.perimeter import get_perimeter_structure_ids

        perim_code = _get_from_db(cur, "perimeter_extraction") or "uca_wide"
        perimeter_ids = get_perimeter_structure_ids(cur, perim_code)
        if perimeter_ids:
            cur.execute(
                """
                SELECT hal_collection, COALESCE(acronym, name) AS label
                FROM structures
                WHERE id = ANY(%s) AND hal_collection IS NOT NULL AND hal_collection != ''
            """,
                (list(perimeter_ids),),
            )
            rows = cur.fetchall()
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
    val = _get_from_db(cur, "hal_collections")
    if val and isinstance(val, dict):
        return val

    return {}


async def async_get_hal_collections(cur: Any) -> dict[str, str]:
    """Variante async de get_hal_collections (§2.12)."""
    try:
        from infrastructure.perimeter import async_get_perimeter_structure_ids

        perim_code = await _async_get_from_db(cur, "perimeter_extraction") or "uca_wide"
        perimeter_ids = await async_get_perimeter_structure_ids(cur, perim_code)
        if perimeter_ids:
            await cur.execute(
                """
                SELECT hal_collection, COALESCE(acronym, name) AS label
                FROM structures
                WHERE id = ANY(%s) AND hal_collection IS NOT NULL AND hal_collection != ''
            """,
                (list(perimeter_ids),),
            )
            rows = await cur.fetchall()
            if rows:
                return {
                    (r["hal_collection"] if isinstance(r, dict) else r[0]): (
                        r["label"] if isinstance(r, dict) else r[1]
                    )
                    for r in rows
                }
    except Exception as e:
        logger.warning(f"Impossible de dériver les collections HAL depuis le périmètre : {e}")

    val = await _async_get_from_db(cur, "hal_collections")
    if val and isinstance(val, dict):
        return val

    return {}


# get_hal_portals supprimé — l'extraction par portail a été retirée,
# seules les collections sont utilisées.


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


def get_api_base_urls(cur: Any) -> dict[str, str]:
    """Retourne les URLs de base des API par source."""
    val = _get_from_db(cur, "api_base_urls")
    if val and isinstance(val, dict):
        return val
    return {
        "hal": "https://api.archives-ouvertes.fr/search/",
        "openalex": "https://api.openalex.org/works",
        "wos": "https://api.clarivate.com/api/wos",
        "scanr": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
        "theses": "https://theses.fr/api/v1/theses/recherche/",
    }


def get_extraction_api_ids(cur: Any, source: str) -> list[str]:
    """Retourne les identifiants API pour une source, déduits du périmètre d'extraction.

    Lit perimeter_extraction → structures du périmètre → api_ids[source].
    Fallback sur les anciennes clés config (openalex_institution_ids, etc.).
    """
    # 1. Depuis les structures du périmètre
    perim_code = _get_from_db(cur, "perimeter_extraction")
    if perim_code and isinstance(perim_code, str):
        try:
            from infrastructure.perimeter import get_perimeter_structure_ids

            struct_ids = get_perimeter_structure_ids(cur, perim_code)
            if struct_ids:
                cur.execute(
                    """
                    SELECT api_ids->%s AS ids
                    FROM structures
                    WHERE id = ANY(%s) AND api_ids ? %s
                """,
                    (source, list(struct_ids), source),
                )
                result = []
                for row in cur.fetchall():
                    ids = row["ids"] if isinstance(row, dict) else row[0]
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
        val = _get_from_db(cur, fallback_key)
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
