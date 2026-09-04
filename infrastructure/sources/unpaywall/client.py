"""Adapter Unpaywall : récupère le statut OA d'un DOI.

API: https://api.unpaywall.org/v2/{doi}?email=...
Rate limit: 100 000 req/jour, ~10 req/s recommandé.

Implémentation async sur `httpx.AsyncClient` + retry/backoff via `http_request_with_retry_async`. Le client httpx est passé en paramètre pour être partagé sur toute la boucle d'enrichissement.
"""

from __future__ import annotations

import logging

import httpx

from domain.publications.identifiers import clean_doi
from domain.types import as_mapping
from infrastructure.sources.http_retry import http_request_with_retry_async

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
    # Re-nettoyage avant l'appel HTTP par DOI (idempotent) : la colonne source peut porter un DOI non normalisé. Un DOI inexploitable → pas d'appel.
    cleaned = clean_doi(doi)
    if not cleaned:
        return None
    url = f"{base_url}/{cleaned}"
    try:
        data = as_mapping(
            await http_request_with_retry_async(
                client,
                "GET",
                url,
                params={"email": email},
                timeout=10,
                label=f"DOI {doi}",
            )
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            logger.warning("  HTTP %s pour %s", e.response.status_code, doi)
        return None
    except httpx.RequestError as e:
        logger.warning("  Erreur réseau pour %s: %s", doi, e)
        return None

    raw_status = data.get("oa_status")
    return OA_MAP.get(raw_status) if isinstance(raw_status, str) else None
