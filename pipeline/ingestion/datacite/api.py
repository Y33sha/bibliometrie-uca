"""Accès à l'API DataCite : en-têtes, moissonnage de `/dois`, lecture des documents par DOI, préfixes.

DataCite reconnaît le polite pool à un `User-Agent` avec mailto. Ses réponses suivent JSON:API.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass

import httpx2

from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.http.polite_pool import polite_user_agent
from pipeline.ingestion.api_params import API_BASE_URLS

# Plafond de l'API DataCite pour la taille d'une page.
_PAGE_SIZE = 1000

RECORD_PARAMS: dict[str, str] = {"affiliation": "true"}
"""Paramètres de toute requête de rapatriement de documents.

`affiliation=true` renvoie les affiliations des créateurs en objets `{name, affiliationIdentifier, affiliationIdentifierScheme}`. Un même DOI garde ainsi la même forme, quelle que soit la route de lecture.
"""


def headers() -> dict[str, str]:
    """Renvoie les en-têtes d'une requête DataCite : `User-Agent` du polite pool, réponse JSON:API."""
    return {
        "User-Agent": polite_user_agent(),
        "Accept": "application/vnd.api+json",
    }


@dataclass(frozen=True)
class DatacitePage:
    """Une page de résultats."""

    records: list[Mapping[str, JsonValue]]
    next_url: str | None
    """URL de la page suivante, `None` en fin de résultats."""


class DataciteClient:
    """Client de `GET /dois`."""

    def __init__(self, base_url: str) -> None:
        self._url = f"{base_url}/dois"
        self._headers = headers()

    def _get(
        self, url: str, params: Mapping[str, str | int] | None, label: str
    ) -> Mapping[str, JsonValue]:
        return as_mapping(
            http_request_with_retry(
                "GET", url, params=params, headers=self._headers, timeout=180, label=label
            )
        )

    def count(self, query: str, label: str) -> int:
        """Renvoie le nombre de DOI désignés par `query`, lu sur une page vide (`page[size]=0`).

        Args:
            label: nom de la requête dans le journal.
        """
        data = self._get(
            self._url,
            {"query": query, "page[size]": 0, **RECORD_PARAMS},
            label=f"({label}, comptage)",
        )
        total = as_mapping(data.get("meta")).get("total")
        return total if isinstance(total, int) else 0

    def fetch_page(
        self, query: str, next_url: str | None, label: str, *, page_size: int = _PAGE_SIZE
    ) -> DatacitePage:
        """Renvoie une page des DOI désignés par `query` : la première quand `next_url` est `None`, sinon la page désignée par `next_url`."""
        if next_url is None:
            data = self._get(
                self._url,
                {"query": query, "page[size]": page_size, "page[cursor]": 1, **RECORD_PARAMS},
                label=f"({label}, première page)",
            )
        else:
            data = self._get(next_url, None, label=f"({label}, page suivante)")
        records = [as_mapping(r) for r in as_sequence(data.get("data"))]
        following = as_str(as_mapping(data.get("links")).get("next"))
        # Une page vide clôt la pagination, même si l'API annonce encore une suite.
        return DatacitePage(records=records, next_url=following if records else None)


async def search_dois(
    client: httpx2.AsyncClient, dois: list[str]
) -> LookupOutcome[list[Mapping[str, JsonValue]]]:
    """Renvoie les documents des DOI d'un lot, par `GET /dois?query=doi:"a" OR doi:"b" …`. Un DOI absent de DataCite manque à la liste.

    Le champ `doi` est requêté en phrase exacte. La liste suit un ordre quelconque.
    """
    clause = " OR ".join(f'doi:"{d}"' for d in dois)
    outcome = await lookup_json_async(
        client,
        "GET",
        f"{API_BASE_URLS['datacite']}/dois",
        params={"query": clause, "page[size]": len(dois), **RECORD_PARAMS},
        headers=headers(),
        timeout=30,
        not_found_statuses=frozenset(),
        label=f"{len(dois)} DOI",
    )
    if isinstance(outcome, NotFound | Unavailable):
        return UNAVAILABLE
    records = as_mapping(outcome).get("data")
    if not isinstance(records, list):
        return UNAVAILABLE
    return [as_mapping(record) for record in records]


async def fetch_doi(client: httpx2.AsyncClient, doi: str) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie la ressource JSON:API `data` de `GET /dois/{doi}`. Un 404 vaut DOI absent de DataCite."""
    outcome = await lookup_json_async(
        client,
        "GET",
        f"{API_BASE_URLS['datacite']}/dois/{urllib.parse.quote(doi, safe='/()')}",
        params=RECORD_PARAMS,
        headers=headers(),
        timeout=30,
        label=f"DOI {doi}",
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    node = as_mapping(outcome).get("data")
    if not isinstance(node, dict):
        return UNAVAILABLE
    return as_mapping(node)


async def fetch_prefix(client: httpx2.AsyncClient, prefix: str) -> LookupOutcome[JsonValue]:
    """Renvoie la réponse JSON:API de `GET /prefixes/{prefix}?include=clients,providers`. Un 400 ou un 404 vaut préfixe inconnu."""
    return await lookup_json_async(
        client,
        "GET",
        f"{API_BASE_URLS['datacite']}/prefixes/{prefix}",
        params={"include": "clients,providers"},
        headers=headers(),
        timeout=15,
        max_retries=3,
        # DataCite répond 400 à chaque appel pour certains préfixes qu'il ne gère pas (10.1713).
        not_found_statuses=frozenset({400, 404}),
        label=f"datacite prefix {prefix}",
    )
