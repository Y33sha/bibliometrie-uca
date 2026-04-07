"""Utilitaires pour la résolution des DOI Zenodo (concept vs version)."""

import re
import requests
from utils.log import setup_logger

logger = setup_logger("zenodo", "processing/logs")

_ZENODO_DOI_RE = re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE)
_API_BASE = "https://zenodo.org/api/records"


def is_zenodo_doi(doi: str | None) -> bool:
    """Vérifie si un DOI est un DOI Zenodo."""
    return bool(doi and _ZENODO_DOI_RE.search(doi))


def resolve_zenodo_doi(doi: str) -> str | None:
    """Résout un DOI Zenodo vers le DOI de la version concrète.

    - Si le DOI est déjà un version DOI, retourne None (rien à changer).
    - Si le DOI est un concept DOI, retourne le version DOI réel.
    - En cas d'erreur API, retourne None (on ne bloque pas la normalisation).
    """
    match = _ZENODO_DOI_RE.search(doi)
    if not match:
        return None

    record_id = match.group(1)
    try:
        resp = requests.get(f"{_API_BASE}/{record_id}", timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            logger.warning(f"Zenodo API {resp.status_code} pour {doi}")
            return None

        data = resp.json()
        real_doi = data.get("doi")
        if real_doi and real_doi.lower() != doi.lower():
            return real_doi

    except Exception as e:
        logger.warning(f"Erreur API Zenodo pour {doi}: {e}")

    return None
