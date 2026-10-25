"""Accès à l'API de recherche de theses.fr : moissonnage, lecture d'une thèse par son identifiant."""

from __future__ import annotations

from collections.abc import Mapping

import httpx2

from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.http_retry import http_request_with_retry, lookup_json_async
from pipeline.http.lookup import NOT_FOUND, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS, THESES_PER_PAGE

# Marge au-dessus d'un hit unique : la recherche libre sur l'identifiant peut ramener quelques quasi-homonymes, filtrés ensuite par égalité stricte de l'`id`.
_SEARCH_SIZE = 20


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
    """Thèse d'identifiant `thesis_id` (NNT d'une thèse soutenue, id theses.fr d'une thèse en cours), ou `NOT_FOUND`.

    L'interrogation passe par l'endpoint de recherche du moissonnage, pour une thèse de même forme, et retient le hit dont l'`id` correspond exactement.
    """
    outcome = await lookup_json_async(
        client,
        "GET",
        API_BASE_URLS["theses"],
        params={"q": thesis_id, "debut": 0, "nombre": _SEARCH_SIZE},
        timeout=30,
        not_found_statuses=frozenset(),
        label=f"these {thesis_id}",
    )
    if isinstance(outcome, NotFound | Unavailable):
        return outcome
    for entry in as_sequence(as_mapping(outcome).get("theses")):
        thesis = as_mapping(entry)
        if as_str(thesis.get("id")) == thesis_id:
            return thesis
    return NOT_FOUND
