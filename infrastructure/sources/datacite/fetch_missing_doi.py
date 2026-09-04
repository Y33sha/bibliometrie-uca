"""Adapter DataCite pour `application.pipeline.cross_imports.fetch_missing_doi`.

DataCite est ingérée DOI-driven : pour les DOI présents dans une autre source mais absents du staging DataCite, on interroge l'endpoint `GET /dois` en **batch** via `query=doi:"a" OR doi:"b" …` (réponse JSON:API, liste de nœuds `data`) et on insère chaque nœud (id + `attributes` + `relationships`) dans `staging` avec `source='datacite'`.

Batch de `batch_size` DOI par requête : la latence DataCite a une falaise nette au-delà d'une dizaine de clauses `OR` (mesuré : ~0,3 s à 10 DOI, ~2,6 s à 20), on reste à 10 — coût par DOI minimal, et c'est alors le rate-limit qui borne. Les DOI absents de la réponse d'un batch sont les introuvables (cf. ci-dessous).

Le pool de DOI candidats est filtré en amont par `get_cross_import_dois` : seuls les DOI dont le préfixe résout à la RA `DataCite` (ou pas encore résolu) sont soumis, ce qui évite les 404 systématiques sur les DOI Crossref.

DataCite est la source native du DOI pour ses préfixes : un miss (DOI absent de la réponse du batch) est définitif (DOI erroné ou non DataCite). Il est mémorisé dans `doi_lookups` avec `next_retry = NULL` (jamais retenté).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.cross_imports.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from domain.publications.identifiers import clean_doi
from domain.types import JsonValue, as_mapping, as_str
from infrastructure.pipeline.extract.cross_import import record_doi_not_found
from infrastructure.pipeline.extract.staging import upsert_staging
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.config import get_polite_pool_email
from infrastructure.sources.http_retry import http_request_with_retry_async
from infrastructure.sources.polite_pool import build_user_agent


def _record_doi(record: Mapping[str, JsonValue]) -> str | None:
    """DOI canonique d'un nœud JSON:API `data` : `attributes.doi`, sinon `id` (les deux portent le DOI). Passé par `clean_doi` (normalisation partagée). `None` si aucun des deux n'est présent ou exploitable."""
    attributes = record.get("attributes")
    doi_raw = as_str(as_mapping(attributes).get("doi")) or as_str(record.get("id")) or ""
    return clean_doi(doi_raw)


class DataciteFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "datacite"
    batch_size = 10
    # Débit DataCite (tier « identifié », User-Agent avec mailto) : 1000 req / 5 min ≈ 3,3 req/s.
    # `max_concurrent=3` × `request_delay_s=0,9` ≈ 3,3 req/s ; chaque requête rapatrie 10 DOI (~33 DOI/s utile).
    max_concurrent = 3
    request_delay_s = 0.9

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = API_BASE_URLS["datacite"]
        email = get_polite_pool_email()
        self.headers = {
            "User-Agent": build_user_agent(email),
            "Accept": "application/vnd.api+json",
        }

    async def fetch_async(
        self, client: httpx.AsyncClient, dois: list[str]
    ) -> Iterable[Mapping[str, JsonValue]]:
        # Batch : `query=doi:"a" OR doi:"b" …`. Le champ `doi` est requêté en phrase exacte ; on remappe ensuite les nœuds reçus aux DOI demandés par comparaison stricte (lowercase), sans se fier à l'ordre ni au volume.
        clause = " OR ".join(f'doi:"{d}"' for d in dois)
        url = f"{self.base_url}/dois"
        try:
            data = as_mapping(
                await http_request_with_retry_async(
                    client,
                    "GET",
                    url,
                    params={"query": clause, "page[size]": len(dois)},
                    headers=self.headers,
                    timeout=30,
                    label=f"{len(dois)} DOI",
                )
            )
        except (httpx.HTTPStatusError, httpx.RequestError):
            # Échec du batch entier : rien remonté, les DOI restent hors staging et seront retentés au prochain run (pool convergent).
            return []

        records = data.get("data")
        if not isinstance(records, list):
            return []

        # DOI demandés non retournés = confirmés absents de DataCite (source native du DOI pour ses préfixes) : miss définitif, stub `staging`.
        found: dict[str, Mapping[str, JsonValue]] = {}
        for rec in records:
            if doi := _record_doi(as_mapping(rec)):
                found[doi] = as_mapping(rec)
        out: list[Mapping[str, JsonValue]] = list(found.values())
        out.extend(not_found_marker(d) for d in dois if clean_doi(d) not in found)
        return out

    def insert(self, conn: Connection, record: Mapping[str, JsonValue]) -> bool:
        if is_not_found_marker(record):
            # Source native du DOI pour ses préfixes : miss définitif → doi_lookups permanent.
            record_doi_not_found(conn, "datacite", as_str(record["_doi"]) or "", permanent=True)
            return False

        # `record` est le nœud JSON:API `data` : son `id` est le DOI, dupliqué dans `attributes.doi`, normalisé en lowercase comme les autres sources.
        doi = _record_doi(record)
        if not doi:
            return False
        inserted, _ = upsert_staging(
            conn,
            source="datacite",
            source_id=doi,
            doi=doi,
            raw_data=record,
            entry_mode="cross_import_doi",
        )
        return inserted
