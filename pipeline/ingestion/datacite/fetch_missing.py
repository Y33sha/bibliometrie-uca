"""Recherche par DOI dans DataCite : tâche `fetch_missing.doi.datacite`.

DataCite est ingérée DOI-driven : pour les DOI présents dans une autre source mais absents du staging DataCite, on interroge l'endpoint `GET /dois` en **batch** via `query=doi:"a" OR doi:"b" …` (réponse JSON:API, liste de tâches `data`) et on insère chaque nœud (id + `attributes` + `relationships`) dans `staging` avec `source='datacite'`.

Batch de `batch_size` DOI par requête : la latence DataCite a une falaise nette au-delà d'une dizaine de clauses `OR` (mesuré : ~0,3 s à 10 DOI, ~2,6 s à 20), on reste à 10 — coût par DOI minimal, et c'est alors le rate-limit qui borne. Les DOI absents de la réponse d'un batch sont les introuvables (cf. ci-dessous).

Le pool de DOI candidats est filtré en amont par `get_missing_dois` : seuls les DOI dont le préfixe résout à la RA `DataCite` (ou pas encore résolu) sont soumis, ce qui évite les 404 systématiques sur les DOI Crossref.

Un DOI absent de la réponse du batch est inscrit dans `failed_lookups`, et `fetch_missing_doi` le soumet à doi.org.
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
    # Débit DataCite (tier « identifié », User-Agent avec mailto) : 1000 req / 5 min ≈ 3,3 req/s.
    # `max_concurrent=3` × `request_delay_s=0,9` ≈ 3,3 req/s ; chaque requête rapatrie 10 DOI (~33 DOI/s utile).
    max_concurrent = 3
    request_delay_s = 0.9

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        records = await search_dois(client, dois)
        if isinstance(records, NotFound | Unavailable):
            return UNAVAILABLE
        # Les nœuds reçus se rapportent aux DOI demandés par comparaison stricte (lowercase), sans se fier à l'ordre ni au volume. DOI demandés non retournés = confirmés absents de DataCite.
        found: dict[str, Mapping[str, JsonValue]] = {}
        for record in records:
            if doi := record_doi(record):
                found[doi] = record
        return LookupBatch(
            records=list(found.values()),
            absent=[d for d in dois if clean_doi(d) not in found],
        )
