"""Accès à l'index Elasticsearch de ScanR : moissonnage et recherche de documents, en authentification basique."""

from __future__ import annotations

from collections.abc import Mapping

import httpx2

from domain.types import JsonValue, as_int, as_mapping, as_sequence, at_path
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.credentials import get_scanr_credentials


class ScanrClient:
    """Client de l'index ScanR (`_search`, authentification basique)."""

    def __init__(self, base_url: str, credentials: tuple[str, str]) -> None:
        self._url = base_url
        self._auth = credentials

    def fetch_page(self, query: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        """Exécute une requête Elasticsearch."""
        return as_mapping(
            http_request_with_retry(
                "POST",
                self._url,
                json_body=query,
                auth=self._auth,
                # Une page de SCANR_PER_PAGE documents peut dépasser 30 s quand le cache du cluster est vide.
                timeout=60,
                label="ScanR search",
            )
        )

    def count(self, query: Mapping[str, JsonValue]) -> int:
        """Nombre de documents de `query`, lu sur un comptage exact sans document (`size=0`)."""
        counting = {**query, "track_total_hits": True, "size": 0}
        return as_int(at_path(self.fetch_page(counting), "hits", "total").get("value")) or 0


async def search(
    client: httpx2.AsyncClient, query: Mapping[str, JsonValue], *, label: str
) -> LookupOutcome[list[Mapping[str, JsonValue]]]:
    """Documents (`_source`) de la requête Elasticsearch `query`. Une réponse valide sans hit rend une liste vide."""
    outcome = await lookup_json_async(
        client,
        "POST",
        API_BASE_URLS["scanr"],
        json_body=query,
        auth=get_scanr_credentials(),
        timeout=30,
        not_found_statuses=frozenset(),
        label=label,
    )
    if isinstance(outcome, NotFound | Unavailable):
        return UNAVAILABLE
    hits = as_sequence(as_mapping(as_mapping(outcome).get("hits")).get("hits"))
    return [as_mapping(as_mapping(hit).get("_source")) for hit in hits]
