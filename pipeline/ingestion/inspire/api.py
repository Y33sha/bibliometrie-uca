"""Accès à l'API de la littérature d'INSPIRE-HEP : recherche paginée, comptage, lecture d'une fiche par son numéro.

Toute requête demande les mêmes champs (`FIELDS`) : une fiche garde ainsi la même forme, quelle que soit la route de lecture. `staging` reçoit le seul `metadata` d'une fiche, sans ses dates de création et de mise à jour.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2

from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS
from pipeline.ingestion.common.pages import Page

FIELDS = ",".join(
    (
        "control_number",
        "titles.title",
        "dois",
        "arxiv_eprints",
        "external_system_identifiers",
        "document_type",
        "publication_info",
        "imprints",
        "preprint_date",
        "earliest_date",
        "abstracts",
        "authors.full_name",
        "authors.first_name",
        "authors.last_name",
        "authors.ids",
        "authors.affiliations",
        "authors.affiliations_identifiers",
        "authors.inspire_roles",
    )
)
"""Champs demandés : ni nombre de citations, ni références, ni affiliations brutes des auteurs."""

PAGE_SIZE = 25
"""Fiches par page. Une fiche de grande collaboration compte trois mille auteurs (environ 1,5 Mo)."""

_HEADERS = {"Accept": "application/json"}


class InspireClient:
    """Client de la recherche dans la littérature (`GET /api/literature`)."""

    def __init__(self) -> None:
        self._url = API_BASE_URLS["inspire"]

    def _get(
        self, url: str, params: Mapping[str, str | int] | None, label: str
    ) -> Mapping[str, JsonValue]:
        return as_mapping(
            http_request_with_retry(
                "GET", url, params=params, headers=_HEADERS, timeout=180, label=label
            )
        )

    def count(self, query: str, label: str) -> int:
        """Renvoie le nombre de fiches désignées par `query`.

        Args:
            label: nom de la requête dans le journal.
        """
        data = self._get(
            self._url,
            {"q": query, "size": 1, "fields": "control_number"},
            label=f"({label}, comptage)",
        )
        total = as_mapping(data.get("hits")).get("total")
        return total if isinstance(total, int) else 0

    def fetch_page(
        self, query: str, next_url: str | None, label: str, *, page_size: int = PAGE_SIZE
    ) -> Page:
        """Renvoie une page des fiches désignées par `query` : la première quand `next_url` est `None`, sinon la page désignée par `next_url`. Le lien de la page suivante garde les paramètres de la requête."""
        if next_url is None:
            data = self._get(
                self._url,
                {"q": query, "size": page_size, "sort": "mostrecent", "fields": FIELDS},
                label=f"({label}, première page)",
            )
        else:
            data = self._get(next_url, None, label=f"({label}, page suivante)")
        hits = as_sequence(as_mapping(data.get("hits")).get("hits"))
        records = [as_mapping(as_mapping(hit).get("metadata")) for hit in hits]
        following = as_str(as_mapping(data.get("links")).get("next"))
        # Une page vide clôt la pagination, même si l'API annonce encore une suite.
        return Page(records, following if records else None)


async def fetch_record(
    client: httpx2.AsyncClient, record_id: str
) -> LookupOutcome[Mapping[str, JsonValue]]:
    """Renvoie le `metadata` de la fiche `GET /api/literature/{numéro}`. Un 404 vaut fiche absente d'INSPIRE."""
    outcome = await lookup_json_async(
        client,
        "GET",
        f"{API_BASE_URLS['inspire']}/{record_id}",
        params={"fields": FIELDS},
        headers=_HEADERS,
        timeout=120,
        label=f"fiche {record_id}",
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    metadata = as_mapping(outcome).get("metadata")
    if not isinstance(metadata, dict):
        return UNAVAILABLE
    return as_mapping(metadata)
