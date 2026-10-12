"""Recherche par DOI dans ScanR : nœud `fetch_missing.doi.scanr`.

API ElasticSearch — requête `terms` sur `externalIds.id.keyword` pour un lot de 50 DOI en un seul appel. Authentification basic.

ScanR stocke les DOI en casse variable : les DOI de ses réponses passent par `clean_doi` avant d'être comparés aux DOI demandés.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.config import get_scanr_credentials
from pipeline.sources.api_params import API_BASE_URLS
from pipeline.sources.failed_lookups import forget_failed_doi_lookups
from pipeline.sources.fetch_missing import DoiBatchResult
from pipeline.sources.http_retry import lookup_json_async
from pipeline.sources.lookup import NotFound, Unavailable
from pipeline.sources.scanr.fields import extract_id
from pipeline.sources.staging import upsert_staging


class ScanrDoiSearch:
    """Recherche par DOI dans ScanR (`DoiSearch`) : requête `terms` sur `externalIds.id.keyword`, par lots."""

    source_key = "scanr"
    batch_size = 50
    # API ElasticSearch publique, pas de rate limit documenté — 5 req concurrentes reste courtois sur une API interne DataESR.
    max_concurrent = 5
    request_delay_s = 0.0

    def __init__(self) -> None:
        self.url = API_BASE_URLS["scanr"]
        self.auth = get_scanr_credentials()

    async def fetch_async(self, client: httpx2.AsyncClient, dois: list[str]) -> DoiBatchResult:
        query: dict[str, JsonValue] = {
            "size": len(dois),
            "query": {"terms": {"externalIds.id.keyword": dois}},
        }
        outcome = await lookup_json_async(
            client,
            "POST",
            self.url,
            json_body=query,
            auth=self.auth,
            timeout=30,
            not_found_statuses=frozenset(),
            label=f"batch {len(dois)} DOI",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return DoiBatchResult()
        records = [
            as_mapping(as_mapping(hit).get("_source"))
            for hit in as_sequence(as_mapping(as_mapping(outcome).get("hits")).get("hits"))
        ]
        # Diff requêtés / trouvés : les DOI du lot sans hit sont confirmés absents de ScanR (réponse ES valide). Comparaison sur DOI nettoyé, cohérente avec les DOI lowercase de `get_missing_dois`.
        found = {
            clean_doi(as_str(champs.get("id")))
            for rec in records
            for ext in as_sequence(rec.get("externalIds"))
            if as_str((champs := as_mapping(ext)).get("type")) == "doi"
        }
        return DoiBatchResult(records=records, not_found=[d for d in dois if d not in found])

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        scanr_id = extract_id(record)
        if not scanr_id:
            return False

        dois = [
            propre
            for entree in as_sequence(record.get("externalIds"))
            if as_str((ext := as_mapping(entree)).get("type")) == "doi"
            and (propre := clean_doi(as_str(ext.get("id"))))
        ]

        inserted, _ = upsert_staging(
            conn,
            source="scanr",
            source_id=scanr_id,
            doi=dois[0] if dois else None,
            raw_data=record,
            entry_mode="fetch_missing_doi",
        )
        # ScanR rend un même document pour chacun de ses DOI : aucun n'est introuvable.
        forget_failed_doi_lookups(conn, "scanr", dois)
        return inserted
