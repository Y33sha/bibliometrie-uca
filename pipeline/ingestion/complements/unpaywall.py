"""Adapter Unpaywall : récupère le statut OA d'un DOI.

API: https://api.unpaywall.org/v2/{doi}?email=...
Rate limit: 100 000 req/jour, ~10 req/s recommandé.

Implémentation async sur `httpx2.AsyncClient` + retry/backoff via `lookup_json_async`. Le client httpx2 est passé en paramètre pour être partagé sur toute la boucle d'enrichissement.
"""

from __future__ import annotations

import httpx2

from domain.publications.identifiers import clean_doi
from domain.types import as_mapping
from pipeline.http.http_retry import lookup_json_async
from pipeline.http.lookup import NOT_FOUND, LookupOutcome, NotFound, Unavailable

# Mapping Unpaywall oa_status → notre enum oa_type
OA_MAP = {
    "gold": "gold",
    "hybrid": "hybrid",
    "bronze": "bronze",
    "green": "green",
    "closed": "closed",
}


async def fetch_oa_status(
    client: httpx2.AsyncClient,
    doi: str,
    *,
    base_url: str,
    email: str,
) -> LookupOutcome[str]:
    """Statut OA d'un DOI selon Unpaywall, ramené au vocabulaire `oa_type`.

    `NOT_FOUND` couvre un DOI inexploitable, un DOI absent d'Unpaywall et un statut hors vocabulaire.
    """
    # Re-nettoyage avant l'appel HTTP par DOI (idempotent) : la colonne source peut porter un DOI non normalisé. Un DOI inexploitable → pas d'appel.
    cleaned = clean_doi(doi)
    if not cleaned:
        return NOT_FOUND
    outcome = await lookup_json_async(
        client,
        "GET",
        f"{base_url}/{cleaned}",
        params={"email": email},
        timeout=10,
        label=f"DOI {doi}",
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    raw_status = as_mapping(outcome).get("oa_status")
    status = OA_MAP.get(raw_status) if isinstance(raw_status, str) else None
    return NOT_FOUND if status is None else status
