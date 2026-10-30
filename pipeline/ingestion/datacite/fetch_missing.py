"""Recherche par DOI dans DataCite : tâche `fetch_missing.doi.datacite`.

Les DOI vus dans une autre source et absents de DataCite sont cherchés par lots : `GET /dois?query=doi:"a" OR doi:"b" …`. Chaque ressource JSON:API reçue s'écrit dans `staging`. Au-delà d'une dizaine de clauses `OR`, la latence de DataCite s'envole (0,3 s à 10 DOI, 2,6 s à 20) : un lot compte donc 10 DOI, et le débit plafonne le coût.

`get_missing_dois` soumet seulement les DOI à préfixe DataCite. Un DOI absent de la réponse de son lot est inscrit dans `failed_lookups`, et `fetch_missing_doi` le soumet à doi.org.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue
from pipeline.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.common.lookup import LookupBatch
from pipeline.ingestion.datacite.api import search_dois
from pipeline.ingestion.datacite.fields import record_doi


class DataciteDoiSearch:
    """Recherche par DOI dans DataCite (`DoiSearch`) : `GET /dois`, par lots."""

    source_key = "datacite"
    batch_size = 10
    max_concurrent = 3

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        records = await search_dois(client, dois)
        if isinstance(records, NotFound | Unavailable):
            return UNAVAILABLE
        # Les ressources reçues se rattachent aux DOI demandés par comparaison exacte en minuscules, quels que soient leur ordre et leur nombre. Un DOI demandé sans ressource est absent de DataCite.
        found: dict[str, Mapping[str, JsonValue]] = {}
        for record in records:
            if doi := record_doi(record):
                found[doi] = record
        return LookupBatch(
            records=list(found.values()),
            absent=[d for d in dois if clean_doi(d) not in found],
        )
