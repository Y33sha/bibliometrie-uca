"""Nouvelle lecture d'un document theses.fr par son identifiant natif : nœud `fetch_stale.theses`.

Refetch d'une row par son identifiant natif (`staging.source_id` : NNT pour une thèse soutenue, id theses.fr pour une thèse en cours). L'interrogation passe par le **même** endpoint recherche que le bulk, pour un `raw_data` de forme identique, et retient le hit dont l'`id` correspond exactement. Une réponse valide sans hit correspondant = identifiant confirmé absent.
"""

from __future__ import annotations

import httpx2

from domain.types import as_mapping, as_sequence, as_str
from infrastructure.sources.api_params import API_BASE_URLS, THESES_DELAY
from infrastructure.sources.http_retry import lookup_json_async
from infrastructure.sources.lookup import NOT_FOUND, NotFound, Unavailable
from pipeline.sources.fetch_stale import FetchedRecord, FetchOutcome, StaleRefetch
from pipeline.sources.theses.fields import extract_doi

# Marge au-dessus d'un hit unique : la recherche libre sur l'identifiant peut ramener quelques quasi-homonymes, filtrés ensuite par égalité stricte de l'`id`.
_SEARCH_SIZE = 20


class ThesesStaleRefetch(StaleRefetch):
    source_key = "theses"
    # theses.fr fragile : un seul worker, cadencé à THESES_DELAY entre appels.
    max_concurrent = 1
    request_delay_s = THESES_DELAY

    def __init__(self) -> None:
        self.url = API_BASE_URLS["theses"]

    async def fetch_by_native_id(self, client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        outcome = await lookup_json_async(
            client,
            "GET",
            self.url,
            params={"q": source_id, "debut": 0, "nombre": _SEARCH_SIZE},
            timeout=30,
            not_found_statuses=frozenset(),
            label=f"these {source_id}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return outcome
        data = as_mapping(outcome)
        for entree in as_sequence(data.get("theses")):
            these = as_mapping(entree)
            if as_str(these.get("id")) == source_id:
                return FetchedRecord(doi=extract_doi(these), raw_data=these)
        return NOT_FOUND
