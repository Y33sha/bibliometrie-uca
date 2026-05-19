"""Adapter Unpaywall : récupère le statut OA d'un DOI.

API: https://api.unpaywall.org/v2/{doi}?email=...
Rate limit: 100 000 req/jour, ~10 req/s recommandé.

Implémentation async sur `httpx.AsyncClient` + retry/backoff via
`http_request_with_retry_async`. Le client httpx est passé en
paramètre pour être partagé sur toute la boucle d'enrichissement.
"""

from __future__ import annotations

import logging

import httpx

from infrastructure.sources.http_retry_async import http_request_with_retry_async

# Mapping Unpaywall oa_status → notre enum oa_type
OA_MAP = {
    "gold": "gold",
    "hybrid": "hybrid",
    "bronze": "bronze",
    "green": "green",
    "closed": "closed",
}


async def fetch_oa_status(
    client: httpx.AsyncClient,
    doi: str,
    *,
    base_url: str,
    email: str,
    logger: logging.Logger,
) -> str | None:
    """Interroge Unpaywall pour un DOI. Retourne le statut OA mappé ou None (DOI inconnu / erreur)."""
    url = f"{base_url}/{doi}"
    try:
        data = await http_request_with_retry_async(
            client,
            "GET",
            url,
            params={"email": email},
            timeout=10,
            label=f"DOI {doi}",
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            logger.warning(f"  HTTP {e.response.status_code} pour {doi}")
        return None
    except httpx.RequestError as e:
        logger.warning(f"  Erreur réseau pour {doi}: {e}")
        return None

    raw_status = data.get("oa_status")
    return OA_MAP.get(raw_status) if isinstance(raw_status, str) else None
