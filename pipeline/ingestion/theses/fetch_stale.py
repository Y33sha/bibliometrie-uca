"""Nouvelle lecture d'un document theses.fr par son identifiant natif : tâche `fetch_stale.theses`.

Refetch d'une row par son identifiant natif (`staging.source_id` : NNT pour une thèse soutenue, id theses.fr pour une thèse en cours). L'interrogation passe par le **même** endpoint recherche que le bulk, pour un `raw_data` de forme identique, et retient le hit dont l'`id` correspond exactement. Une réponse valide sans hit correspondant = identifiant confirmé absent.
"""

from __future__ import annotations

import httpx2

from domain.types import as_mapping, as_sequence, as_str
from pipeline.http.http_retry import lookup_json_async
from pipeline.http.lookup import NOT_FOUND, NotFound, Unavailable
from pipeline.ingestion.api_params import API_BASE_URLS, THESES_DELAY
from pipeline.ingestion.common.stale_refetch import FetchedRecord, FetchOutcome, StaleRefetch
from pipeline.ingestion.theses.fields import extract_doi

# Marge au-dessus d'un hit unique : la recherche libre sur l'identifiant peut ramener quelques quasi-homonymes, filtrés ensuite par égalité stricte de l'`id`.
_SEARCH_SIZE = 20


async def fetch_thesis(client: httpx2.AsyncClient, thesis_id: str) -> FetchOutcome:
    """Document theses.fr d'identifiant `thesis_id` (NNT d'une thèse soutenue, id theses.fr d'une thèse en cours), ou `NOT_FOUND`."""
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
    data = as_mapping(outcome)
    for entree in as_sequence(data.get("theses")):
        these = as_mapping(entree)
        if as_str(these.get("id")) == thesis_id:
            return FetchedRecord(doi=extract_doi(these), raw_data=these)
    return NOT_FOUND


class ThesesStaleRefetch(StaleRefetch):
    source_key = "theses"
    # theses.fr fragile : un seul worker, cadencé à THESES_DELAY entre appels.
    max_concurrent = 1
    request_delay_s = THESES_DELAY

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        return await fetch_thesis(client, source_id)
