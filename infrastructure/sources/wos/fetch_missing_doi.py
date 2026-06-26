"""Adapter WoS pour `application.pipeline.extract.fetch_missing_doi`.

WoS accepte une requête groupée par DOI (`DO=("doi1" OR "doi2" OR ...)`).
Lot de 20 DOI par requête pour éviter des URLs trop longues, pagination
interne de `WOS_PER_PAGE` records, retries exponentiels sur 429/erreurs.

Certains DOI (preprints Zenodo, arXiv, SSRN, Research Square...) sont
systématiquement absents de WoS : on les filtre côté client pour éviter
les appels inutiles.

Adapter async (`AsyncFetchMissingDoiAdapter`). Les requêtes DOI
individuelles (via batch de 20 et WOS_PER_PAGE=10) sont stables ;
les pages larges de l'API WoS le sont moins.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable

import httpx
from sqlalchemy import Connection

from application.ports.pipeline.extract.fetch_missing_doi import (
    is_not_found_marker,
    not_found_marker,
)
from infrastructure.sources.api_limits import WOS_DELAY, WOS_PER_PAGE
from infrastructure.sources.common import record_doi_not_found, upsert_staging
from infrastructure.sources.config import get_api_base_urls, get_wos_api_key
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.wos.parsing import extract_doi, extract_ut, filter_doi_for_wos

log = logging.getLogger(__name__)


class WosFetchMissingDoiAdapter:
    """Adapter async conforme au `AsyncFetchMissingDoiAdapter` Protocol."""

    source_key = "wos"
    batch_size = 20
    # WoS API Clarivate : instable historiquement et rate-limit serré
    # (variable selon contrat, généralement 2-5 req/s). 2 workers + 500 ms
    # de pause par worker garantissent un débit ≈ 2 req/s peak (avec
    # latence WoS typique ~500 ms), sous le seuil habituel et sans burst
    # initial.
    max_concurrent = 2
    request_delay_s = 0.5

    base_url: str
    headers: dict[str, str]

    def configure(self, conn: Connection) -> None:
        self.base_url = get_api_base_urls()["wos"]
        self.headers = {"X-ApiKey": get_wos_api_key(conn), "Accept": "application/json"}

    async def fetch_async(self, client: httpx.AsyncClient, dois: list[str]) -> Iterable[dict]:
        # (doi d'origine, forme envoyable à WoS ou None si filtré). Les DOI
        # preprints filtrés (c=None) ne sont pas interrogeables, donc jamais
        # enregistrés comme not-found (le filtre client les écarte gratuitement).
        queried = [(d, filter_doi_for_wos(d)) for d in dois]
        clean = [c for _, c in queried if c]

        records: list[dict] = []
        # complete : a-t-on un résultat fiable pour calculer les not-found ?
        # Mis à False sur tout arrêt prématuré (erreur réseau, corps vide,
        # réponse mal formée) où l'absence d'un DOI ne prouve rien.
        complete = True
        first_record = 1
        while clean:
            query = "DO=(" + " OR ".join(f'"{d}"' for d in clean) + ")"
            params = {
                "databaseId": "WOS",
                "usrQuery": query,
                "count": WOS_PER_PAGE,
                "firstRecord": first_record,
            }
            try:
                data = await http_request_with_retry_async(
                    client,
                    "GET",
                    self.base_url,
                    headers=self.headers,
                    params=params,
                    timeout=60,
                    # Backoff initial 4s pour matcher le comportement sync historique
                    # (2^(attempt+2) = 4, 8, 16, 32, 64)
                    initial_backoff=4.0,
                    retry_on_empty_body=True,
                    label=f"rec {first_record}",
                )
            except httpx.HTTPStatusError as e:
                # WoS 400 = lot sans correspondance : zéro match, le lot entier
                # est confirmé absent (résultat fiable → on garde complete=True).
                if e.response.status_code == 400:
                    log.warning("WoS 400 rec %d, lot ignoré", first_record)
                    break
                raise
            except httpx.RequestError:
                complete = False
                break

            if not data:
                complete = False
                break
            try:
                recs_container = data.get("Data", {}).get("Records", {})
                if not isinstance(recs_container, dict):
                    complete = False
                    break
                recs = recs_container.get("records", {})
                if not isinstance(recs, dict):
                    complete = False
                    break
                recs = recs.get("REC", [])
            except (AttributeError, TypeError):
                complete = False
                break
            if isinstance(recs, dict):
                recs = [recs]
            if not recs:
                break
            records.extend(recs)

            total = int(data.get("QueryResult", {}).get("RecordsFound", 0))
            if first_record + WOS_PER_PAGE - 1 >= total:
                break
            first_record += WOS_PER_PAGE
            await asyncio.sleep(WOS_DELAY)

        if not complete:
            return records
        # Lot complet : tout DOI interrogé sans record correspondant est
        # confirmé absent de WoS. `extract_doi` et les candidats sont tous deux
        # normalisés par `clean_doi`, donc comparables directement.
        found = {d for r in records if (d := extract_doi(r))}
        missed = [not_found_marker(orig) for orig, c in queried if c and c not in found]
        return records + missed

    def insert(self, conn: Connection, record: dict) -> bool:
        if is_not_found_marker(record):
            record_doi_not_found(conn, "wos", record["_doi"])
            conn.commit()
            return False

        inserted, _ = upsert_staging(
            conn,
            source="wos",
            source_id=extract_ut(record),
            doi=extract_doi(record),
            raw_data=record,
            entry_mode="cross_import_doi",
        )
        conn.commit()
        return inserted
