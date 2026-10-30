"""Accès à l'API Crossref : en-têtes, moissonnage de `/works`, lecture d'une ressource par son chemin.

Crossref reconnaît le polite pool à un `User-Agent` avec mailto.
"""

from __future__ import annotations

import logging
import urllib.parse
from collections.abc import Mapping

import httpx2

from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.http.polite_pool import polite_user_agent
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.person_search import PersonSearchPage

logger = logging.getLogger(__name__)

# Documents par page. Un document de grande collaboration pèse environ 500 Kio, et Crossref refuse une réponse de plus de 100 Mio.
_ROWS = 50


def headers() -> dict[str, str]:
    """Renvoie les en-têtes d'une requête Crossref : `User-Agent` du polite pool, réponse JSON."""
    return {"User-Agent": polite_user_agent(), "Accept": "application/json"}


class CrossrefClient:
    """Client de `GET /works`."""

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url}/works"
        self._headers = headers()

    def fetch_page(self, filters: str, cursor: str | None, label: str) -> PersonSearchPage:
        """Renvoie une page des œuvres désignées par `filters`, la première quand `cursor` est `None`. Une page vide clôt la pagination."""
        data = as_mapping(
            http_request_with_retry(
                "GET",
                self._url,
                params={"filter": filters, "rows": _ROWS, "cursor": cursor or "*"},
                headers=self._headers,
                timeout=120,
                label=label,
            )
        )
        message = as_mapping(data.get("message"))
        records = [as_mapping(item) for item in as_sequence(message.get("items"))]
        following = as_str(message.get("next-cursor"))
        return PersonSearchPage(records=records, next_token=following if records else None)


async def get_message(
    client: httpx2.AsyncClient,
    path: str,
    *,
    label: str,
    timeout: float = 30.0,  # noqa: ASYNC109 — transmis au client httpx2
    max_retries: int = 3,
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie le corps `message` de `GET <racine>/<path>`. Une réponse sans `message` compte pour une source indisponible."""
    url = f"{API_BASE_URLS['crossref']}/{path}"
    outcome = await lookup_json_async(
        client,
        "GET",
        url,
        headers=headers(),
        timeout=timeout,
        max_retries=max_retries,
        label=label,
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    message = as_mapping(outcome).get("message")
    if not isinstance(message, dict):
        logger.warning("%s : réponse sans `message`", url)
        return UNAVAILABLE
    return as_mapping(message)


async def fetch_work(
    client: httpx2.AsyncClient, doi: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie le document de `GET /works/{doi}`. Crossref accepte le DOI tel quel dans le chemin, barres obliques comprises."""
    return await get_message(
        client, f"works/{urllib.parse.quote(doi, safe='/()')}", label=f"DOI {doi}"
    )
