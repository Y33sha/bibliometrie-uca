"""Client doi.org/ra : Registration Agency d'un DOI.

`doi.org/ra/<doi>` renvoie l'agence d'enregistrement d'un DOI (`Crossref`, `DataCite`, `mEDRA`, `unknown`, …). Une RA est permanente à l'échelle d'un préfixe (un préfixe = un registrant = une RA) : un seul appel par préfixe suffit côté pipeline, mais plusieurs DOI samples par préfixe se prémunissent d'un DOI erroné dans le staging. Interrogé par la phase `resolve_ra`. Polite pool via header `User-Agent` (mailto).
"""

from __future__ import annotations

import logging
import urllib.parse

from domain.publications.identifiers import clean_doi
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.http_retry import http_request_with_retry

logger = logging.getLogger(__name__)

# Sentinelle renvoyée par doi.org/ra quand le DOI fourni n'existe pas.
_DOI_NOT_FOUND = "DOI Not Found"


def resolve_ra(doi: str, *, user_agent: str) -> str | None:
    """Interroge `doi.org/ra` pour récupérer la Registration Agency d'un DOI.

    Renvoie le nom de la RA (`'Crossref'`, `'DataCite'`, `'mEDRA'`, `'unknown'`, …) ou `None` si la résolution échoue (DOI inconnu, erreur réseau/HTTP). Le caller doit retenter avec un autre DOI du même préfixe si `None`.

    `'unknown'` est une valeur valide renvoyée par doi.org pour un préfixe enregistré chez une RA hors du set principal, distincte de la non-résolution (qui renvoie `None`).
    """
    cleaned = clean_doi(doi)
    if not cleaned:
        return None
    url = f"{API_BASE_URLS['doi_org']}/{urllib.parse.quote(cleaned, safe='')}"
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    try:
        data = http_request_with_retry(
            "GET", url, headers=headers, timeout=15, max_retries=3, label=f"DOI {doi}"
        )
    except Exception as exc:
        logger.warning("doi.org/ra %s : %r", doi, exc)
        return None
    if not isinstance(data, list) or not data:
        return None
    ra = data[0].get("RA") if isinstance(data[0], dict) else None
    if not isinstance(ra, str) or not ra or ra == _DOI_NOT_FOUND:
        return None
    return ra
