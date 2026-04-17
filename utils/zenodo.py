"""Utilitaires pour la résolution des DOI Zenodo (concept vs version)."""

import re
import time

import requests

from utils.api_limits import ZENODO_DELAY
from utils.log import setup_logger

logger = setup_logger("zenodo", "processing/logs")

_ZENODO_DOI_RE = re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE)
_API_BASE = "https://zenodo.org/api/records"
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 2  # secondes
_last_request_time = 0.0


def is_zenodo_doi(doi: str | None) -> bool:
    """Vérifie si un DOI est un DOI Zenodo."""
    return bool(doi and _ZENODO_DOI_RE.search(doi))


class ZenodoResolutionError(Exception):
    """Erreur temporaire de résolution Zenodo (rate-limit, timeout)."""
    pass


def resolve_zenodo_doi(doi: str) -> str | None:
    """Résout un DOI Zenodo vers le DOI de la version concrète.

    - Si le DOI est déjà un version DOI, retourne None (rien à changer).
    - Si le DOI est un concept DOI, retourne le version DOI réel.
    - Lève ZenodoResolutionError en cas d'erreur temporaire (429, timeout)
      pour que l'appelant puisse décider de ne pas marquer processed.
    - Retry avec backoff exponentiel en cas de 429 (rate limit).
    """
    match = _ZENODO_DOI_RE.search(doi)
    if not match:
        return None

    record_id = match.group(1)
    backoff = _INITIAL_BACKOFF

    global _last_request_time
    for attempt in range(_MAX_RETRIES):
        try:
            # Délai de politesse
            elapsed = time.time() - _last_request_time
            if elapsed < ZENODO_DELAY:
                time.sleep(ZENODO_DELAY - elapsed)

            resp = requests.get(f"{_API_BASE}/{record_id}", timeout=10,
                                allow_redirects=True)
            _last_request_time = time.time()
            if resp.status_code == 429:
                wait = backoff * (2 ** attempt)
                logger.info(f"Zenodo 429 pour {doi}, attente {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code in (410, 404):
                # Document supprimé ou introuvable — pas temporaire
                logger.warning(f"Zenodo API {resp.status_code} pour {doi}")
                return None

            if resp.status_code != 200:
                logger.warning(f"Zenodo API {resp.status_code} pour {doi}")
                raise ZenodoResolutionError(f"HTTP {resp.status_code}")

            data = resp.json()
            real_doi = data.get("doi")
            if real_doi and real_doi.lower() != doi.lower():
                return real_doi
            return None

        except requests.exceptions.RequestException as e:
            logger.warning(f"Erreur API Zenodo pour {doi}: {e}")
            raise ZenodoResolutionError(str(e))

    logger.warning(f"Zenodo API : abandon après {_MAX_RETRIES} tentatives pour {doi}")
    raise ZenodoResolutionError(f"rate-limited après {_MAX_RETRIES} tentatives")
