"""Client Unpaywall : statut open access d'un DOI.

L'API (`https://api.unpaywall.org/v2/{doi}?email=…`) accepte 100 000 requêtes par jour, et recommande une dizaine par seconde. Les requêtes passent par `lookup_json_async`, avec nouvelles tentatives et backoff, sur un client que toute la boucle d'enrichissement partage.
"""

from __future__ import annotations

import httpx2

from domain.publications.identifiers import clean_doi
from domain.types import as_mapping
from pipeline.http.http_retry import lookup_json_async
from pipeline.http.lookup import NOT_FOUND, LookupOutcome, NotFound, Unavailable

# Statut Unpaywall → `oa_type`.
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
    """Statut open access d'un DOI selon Unpaywall, ramené au vocabulaire `oa_type`.

    `NOT_FOUND` couvre un DOI inexploitable, un DOI absent d'Unpaywall et un statut hors vocabulaire.
    """
    # La colonne d'origine peut contenir un DOI non normalisé : `clean_doi` repasse avant l'appel. Un DOI inexploitable évite l'appel.
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
