"""Lecture de la configuration applicative.

Lit depuis la table `config` en base, avec fallback sur `config/settings.py`.
Les scripts du pipeline appellent ce module au lieu de lire settings.py directement
pour les paramètres externalisés (années, collections, affiliations).
"""

import datetime
import json
import logging

logger = logging.getLogger(__name__)


def _get_from_db(cur, key):
    """Lit une valeur depuis la table config. Retourne None si absente."""
    try:
        cur.execute("SELECT value FROM config WHERE key = %s", (key,))
        row = cur.fetchone()
        if row:
            return row[0] if isinstance(row, tuple) else row["value"]
    except Exception:
        pass
    return None


def get_years(cur, mode: str = "full") -> list[int]:
    """Retourne la liste des années à extraire selon le mode.

    Lit pipeline_years_full ou pipeline_years_weekly depuis la table config.
    Fallback sur config/settings.py si la table config n'existe pas.
    """
    key = "pipeline_years_weekly" if mode == "weekly" else "pipeline_years_full"
    offset = _get_from_db(cur, key)

    if offset is not None:
        try:
            n = int(offset) if not isinstance(offset, int) else offset
            current_year = datetime.date.today().year
            return list(range(current_year - n, current_year + 1))
        except (ValueError, TypeError):
            logger.warning(f"Valeur invalide pour {key}: {offset}")

    # Fallback settings.py
    try:
        from config.settings import OPENALEX
        return OPENALEX.get("years", [datetime.date.today().year])
    except ImportError:
        current_year = datetime.date.today().year
        return [current_year]


def get_hal_collections(cur) -> dict[str, str]:
    """Retourne les collections HAL {code_hal: label}.

    Dérivé des structures du périmètre UCA qui ont un hal_collection renseigné.
    Fallback sur la table config, puis sur settings.py.
    """
    # 1. Depuis les structures du périmètre UCA
    try:
        from utils.uca_perimeter import get_uca_structure_ids
        uca_ids = get_uca_structure_ids(cur)
        if uca_ids:
            cur.execute("""
                SELECT hal_collection, COALESCE(acronym, name) AS label
                FROM structures
                WHERE id = ANY(%s) AND hal_collection IS NOT NULL AND hal_collection != ''
            """, (list(uca_ids),))
            rows = cur.fetchall()
            if rows:
                return {(r["hal_collection"] if isinstance(r, dict) else r[0]): (r["label"] if isinstance(r, dict) else r[1]) for r in rows}
    except Exception as e:
        logger.warning(f"Impossible de dériver les collections HAL depuis le périmètre : {e}")

    # 2. Fallback config DB
    val = _get_from_db(cur, "hal_collections")
    if val and isinstance(val, dict):
        return val

    # 3. Fallback settings.py
    try:
        from config.settings import HAL
        return HAL.get("collections", {})
    except ImportError:
        return {}


def get_hal_portal(cur) -> str:
    """Retourne le portail HAL global."""
    val = _get_from_db(cur, "hal_portal")
    if val and isinstance(val, str):
        return val

    try:
        from config.settings import HAL
        return HAL.get("portal", "clermont-univ")
    except ImportError:
        return "clermont-univ"


def get_openalex_institution_ids(cur) -> list[str]:
    """Retourne les IDs institution OpenAlex."""
    val = _get_from_db(cur, "openalex_institution_ids")
    if val and isinstance(val, list):
        return val

    try:
        from config.settings import OPENALEX
        ids = OPENALEX.get("institution_ids") or [OPENALEX.get("institution_id")]
        return [i for i in ids if i]
    except ImportError:
        return ["i198244214"]


def get_wos_affiliations(cur) -> list[str]:
    """Retourne les noms OG WoS."""
    val = _get_from_db(cur, "wos_affiliations")
    if val and isinstance(val, list):
        return val

    try:
        from config.settings import WOS
        return WOS.get("affiliations", [])
    except ImportError:
        return []


def get_openalex_email(cur) -> str:
    """Retourne l'email pour le polite pool OpenAlex."""
    val = _get_from_db(cur, "openalex_email")
    if val and isinstance(val, str):
        return val

    try:
        from config.settings import OPENALEX
        return OPENALEX.get("email", "bibliometrie@uca.fr")
    except ImportError:
        return "bibliometrie@uca.fr"


def get_wos_api_key(cur) -> str:
    """Retourne la clé API WoS."""
    val = _get_from_db(cur, "wos_api_key")
    if val and isinstance(val, str):
        return val

    try:
        from config.settings import WOS
        return WOS.get("api_key", "")
    except ImportError:
        return ""


def get_scanr_affiliation_ids(cur) -> list[str]:
    """Retourne les IDs SIREN des structures ScanR."""
    val = _get_from_db(cur, "scanr_affiliation_ids")
    if val and isinstance(val, list):
        return val

    try:
        from config.settings import SCANR
        return SCANR.get("affiliation_ids", [])
    except ImportError:
        return []


def get_theses_etab_ppns(cur) -> list[str]:
    """Retourne les PPN IdRef des établissements de soutenance pour theses.fr."""
    val = _get_from_db(cur, "theses_etab_ppns")
    if val and isinstance(val, list):
        return val

    try:
        from config.settings import THESES
        return THESES.get("etab_ppns", [])
    except ImportError:
        return []


def get_scanr_credentials(cur) -> tuple[str, str]:
    """Retourne (username, password) pour l'API ScanR."""
    user = _get_from_db(cur, "scanr_username")
    pwd = _get_from_db(cur, "scanr_password")
    if user and pwd:
        return user, pwd

    try:
        from config.settings import SCANR
        return SCANR.get("username", ""), SCANR.get("password", "")
    except ImportError:
        return "", ""
