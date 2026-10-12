"""Recherche par DOI dans DataCite : nœud `fetch_missing.doi.datacite`.

DataCite est ingérée DOI-driven : pour les DOI présents dans une autre source mais absents du staging DataCite, on interroge l'endpoint `GET /dois` en **batch** via `query=doi:"a" OR doi:"b" …` (réponse JSON:API, liste de nœuds `data`) et on insère chaque nœud (id + `attributes` + `relationships`) dans `staging` avec `source='datacite'`.

Batch de `batch_size` DOI par requête : la latence DataCite a une falaise nette au-delà d'une dizaine de clauses `OR` (mesuré : ~0,3 s à 10 DOI, ~2,6 s à 20), on reste à 10 — coût par DOI minimal, et c'est alors le rate-limit qui borne. Les DOI absents de la réponse d'un batch sont les introuvables (cf. ci-dessous).

Le pool de DOI candidats est filtré en amont par `get_missing_dois` : seuls les DOI dont le préfixe résout à la RA `DataCite` (ou pas encore résolu) sont soumis, ce qui évite les 404 systématiques sur les DOI Crossref.

DataCite est la source native du DOI pour ses préfixes : un DOI absent de la réponse du batch est définitivement introuvable (DOI erroné ou non DataCite). `record_failed_lookup` l'inscrit dans `failed_lookups` sans date de nouvelle tentative.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping
from pipeline.sources.api_params import API_BASE_URLS
from pipeline.sources.datacite.fields import RECORD_PARAMS, api_headers, record_doi
from pipeline.sources.failed_lookups import forget_failed_doi_lookups
from pipeline.sources.fetch_missing import DoiBatchResult
from pipeline.sources.http_retry import lookup_json_async
from pipeline.sources.lookup import NotFound, Unavailable
from pipeline.sources.staging import upsert_staging


class DataciteDoiSearch:
    """Recherche par DOI dans DataCite (`DoiSearch`) : `GET /dois`, par lots."""

    source_key = "datacite"
    batch_size = 10
    # Débit DataCite (tier « identifié », User-Agent avec mailto) : 1000 req / 5 min ≈ 3,3 req/s.
    # `max_concurrent=3` × `request_delay_s=0,9` ≈ 3,3 req/s ; chaque requête rapatrie 10 DOI (~33 DOI/s utile).
    max_concurrent = 3
    request_delay_s = 0.9

    def __init__(self) -> None:
        self.base_url = API_BASE_URLS["datacite"]
        self.headers = api_headers()

    async def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> DoiBatchResult:
        # Batch : `query=doi:"a" OR doi:"b" …`. Le champ `doi` est requêté en phrase exacte ; on remappe ensuite les nœuds reçus aux DOI demandés par comparaison stricte (lowercase), sans se fier à l'ordre ni au volume.
        clause = " OR ".join(f'doi:"{d}"' for d in dois)
        outcome = await lookup_json_async(
            client,
            "GET",
            f"{self.base_url}/dois",
            params={"query": clause, "page[size]": len(dois), **RECORD_PARAMS},
            headers=self.headers,
            timeout=30,
            not_found_statuses=frozenset(),
            label=f"{len(dois)} DOI",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return DoiBatchResult()
        records = as_mapping(outcome).get("data")
        if not isinstance(records, list):
            return DoiBatchResult()

        # DOI demandés non retournés = confirmés absents de DataCite.
        found: dict[str, Mapping[str, JsonValue]] = {}
        for rec in records:
            if doi := record_doi(as_mapping(rec)):
                found[doi] = as_mapping(rec)
        return DoiBatchResult(
            records=list(found.values()),
            not_found=[d for d in dois if clean_doi(d) not in found],
        )

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        # `record` est le nœud JSON:API `data` : son `id` est le DOI, dupliqué dans `attributes.doi`, normalisé en lowercase comme les autres sources.
        doi = record_doi(record)
        if not doi:
            return False
        inserted, _ = upsert_staging(
            conn,
            source="datacite",
            source_id=doi,
            doi=doi,
            raw_data=record,
            entry_mode="fetch_missing_doi",
        )
        forget_failed_doi_lookups(conn, "datacite", [doi])
        return inserted
