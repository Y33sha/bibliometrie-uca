"""Recherche par DOI dans ScanR : tâche `fetch_missing.doi.scanr`.

API ElasticSearch — requête `terms` sur `externalIds.id.keyword` pour un lot de 50 DOI en un seul appel. Authentification basic.

ScanR stocke les DOI en casse variable : les DOI de ses réponses passent par `clean_doi` avant d'être comparés aux DOI demandés.
"""

from __future__ import annotations

import httpx2

from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_sequence, as_str
from pipeline.http.lookup import UNAVAILABLE, NotFound, Unavailable
from pipeline.ingestion.common.lookup import LookupBatch
from pipeline.ingestion.scanr.api import search


class ScanrDoiSearch:
    """Recherche par DOI dans ScanR (`DoiSearch`) : requête `terms` sur `externalIds.id.keyword`, par lots."""

    source_key = "scanr"
    batch_size = 50
    # API ElasticSearch publique, pas de rate limit documenté — 5 req concurrentes reste courtois sur une API interne DataESR.
    max_concurrent = 5

    async def fetch_async(
        self, client: httpx2.AsyncClient, dois: list[str]
    ) -> LookupBatch | Unavailable:
        query: dict[str, JsonValue] = {
            "size": len(dois),
            "query": {"terms": {"externalIds.id.keyword": dois}},
        }
        records = await search(client, query, label=f"batch {len(dois)} DOI")
        if isinstance(records, NotFound | Unavailable):
            return UNAVAILABLE
        # Diff requêtés / trouvés : les DOI du lot sans hit sont confirmés absents de ScanR (réponse ES valide). Comparaison sur DOI nettoyé, cohérente avec les DOI lowercase de `get_missing_dois`.
        found = {
            clean_doi(as_str(fields.get("id")))
            for rec in records
            for ext in as_sequence(rec.get("externalIds"))
            if as_str((fields := as_mapping(ext)).get("type")) == "doi"
        }
        return LookupBatch(records=records, absent=[d for d in dois if d not in found])
