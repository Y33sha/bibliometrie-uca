"""Accès à l'API de theses.fr : recherche des thèses d'un établissement, détail d'une thèse par son identifiant."""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote

import httpx2

from domain.types import JsonValue, as_mapping
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS, THESES_PER_PAGE


class ThesesClient:
    """Client de la recherche theses.fr."""

    def __init__(self, base_url: str) -> None:
        self._url = base_url

    def fetch_page(self, query: str, *, start: int) -> Mapping[str, JsonValue]:
        """Une page de `THESES_PER_PAGE` thèses, à partir du rang `start`."""
        params: dict[str, str | int | float | bool | None] = {
            "q": query,
            "debut": start,
            "nombre": THESES_PER_PAGE,
        }
        return as_mapping(
            http_request_with_retry(
                "GET", self._url, params=params, timeout=30, label=f"theses debut={start}"
            )
        )


async def fetch_thesis(
    client: httpx2.AsyncClient, thesis_id: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Détail de la thèse d'identifiant `thesis_id` (NNT d'une thèse soutenue, identifiant theses.fr d'une thèse en cours), ou `NOT_FOUND`.

    theses.fr répond 400 pour un identifiant inconnu.
    """
    outcome = await lookup_json_async(
        client,
        "GET",
        API_BASE_URLS["theses_detail"] + quote(thesis_id, safe=""),
        timeout=30,
        not_found_statuses=frozenset({400, 404}),
        label=f"these {thesis_id}",
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    return as_mapping(outcome)
