"""Adapter WoS pour `application.pipeline.fetch_missing_doi`.

WoS accepte une requête groupée par DOI (`DO=("doi1" OR "doi2" OR ...)`).
Lot de 20 DOI par requête pour éviter des URLs trop longues, pagination
interne de `WOS_PER_PAGE` records, retries exponentiels sur 429/erreurs.

Certains DOI (preprints Zenodo, arXiv, SSRN, Research Square...) sont
systématiquement absents de WoS : on les filtre côté client pour éviter
les appels inutiles.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterable

import requests
from psycopg.types.json import Jsonb as Json

from infrastructure.api_limits import WOS_DELAY, WOS_PER_PAGE
from infrastructure.app_config import get_api_base_urls, get_wos_api_key
from infrastructure.sources.common import compute_hash

log = logging.getLogger(__name__)


def _clean_doi_for_wos(doi: str) -> str | None:
    doi = re.split(r"[&?]", doi.strip())[0]
    skip_prefixes = ("10.48550/", "10.2139/", "10.21203/", "10.5281/zenodo")
    if any(doi.lower().startswith(p) for p in skip_prefixes):
        return None
    if '"' in doi or "\n" in doi:
        return None
    return doi


def _extract_ut(rec: dict) -> str:
    return rec["UID"]


def _extract_doi(rec: dict) -> str | None:
    try:
        identifiers = (
            rec.get("dynamic_data", {})
            .get("cluster_related", {})
            .get("identifiers", {})
            .get("identifier", [])
        )
        if isinstance(identifiers, dict):
            identifiers = [identifiers]
        if not isinstance(identifiers, list):
            return None
        for ident in identifiers:
            if isinstance(ident, dict) and ident.get("type") == "doi":
                val = ident.get("value")
                return str(val).strip() if val is not None else None
    except (KeyError, TypeError, AttributeError):
        pass
    return None


class WosFetchMissingDoiAdapter:
    source_key = "wos"
    rate_delay = WOS_DELAY
    batch_size = 20

    base_url: str
    headers: dict[str, str]

    def configure(self, cur: Any) -> None:
        self.base_url = get_api_base_urls(cur).get(
            "wos", "https://api.clarivate.com/api/wos"
        )
        self.headers = {"X-ApiKey": get_wos_api_key(cur), "Accept": "application/json"}

    def fetch(self, dois: list[str]) -> Iterable[dict]:
        clean = [d for d in (_clean_doi_for_wos(x) for x in dois) if d]
        if not clean:
            return []
        query = "DO=(" + " OR ".join(f'"{d}"' for d in clean) + ")"

        records: list[dict] = []
        first_record = 1
        while True:
            params = {
                "databaseId": "WOS",
                "usrQuery": query,
                "count": WOS_PER_PAGE,
                "firstRecord": first_record,
            }
            data = self._fetch_with_retry(params, label=f"rec {first_record}")
            if not data:
                break
            try:
                recs_container = data.get("Data", {}).get("Records", {})
                if not isinstance(recs_container, dict):
                    break
                recs = recs_container.get("records", {})
                if not isinstance(recs, dict):
                    break
                recs = recs.get("REC", [])
            except (AttributeError, TypeError):
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
            time.sleep(self.rate_delay)

        return records

    def _fetch_with_retry(self, params: dict, *, label: str) -> dict:
        for attempt in range(5):
            try:
                resp = requests.get(
                    self.base_url, headers=self.headers, params=params, timeout=60
                )
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 2)
                    log.warning("WoS 429 %s, attente %ds", label, wait)
                    time.sleep(wait)
                    continue
                if resp.status_code == 400:
                    log.warning("WoS 400 %s, lot ignoré", label)
                    return {}
                resp.raise_for_status()
                if not resp.text.strip():
                    wait = 2 ** (attempt + 1)
                    log.warning(
                        "WoS réponse vide %s (%d/5), attente %ds", label, attempt + 1, wait
                    )
                    time.sleep(wait)
                    continue
                return resp.json()
            except requests.exceptions.JSONDecodeError:
                wait = 2 ** (attempt + 1)
                log.warning("WoS JSON invalide %s (%d/5), attente %ds", label, attempt + 1, wait)
                time.sleep(wait)
            except requests.RequestException as e:
                if attempt < 4:
                    wait = 2 ** (attempt + 1)
                    log.warning("WoS erreur %s (%d/5): %s", label, attempt + 1, e)
                    time.sleep(wait)
                else:
                    raise
        log.error("WoS échec après 5 tentatives %s", label)
        return {}

    def insert(self, conn: Any, record: dict) -> bool:
        ut = _extract_ut(record)
        doi = _extract_doi(record)
        raw_hash = compute_hash(record)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
                VALUES ('wos', %s, %s, %s, %s)
                ON CONFLICT (source, source_id) DO UPDATE SET
                    raw_data = CASE
                        WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN EXCLUDED.raw_data ELSE staging.raw_data END,
                    raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
                    processed = CASE
                        WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                        THEN FALSE ELSE staging.processed END,
                    last_seen_at = now()
                """,
                (ut, doi, Json(record), raw_hash),
            )
            inserted = cur.rowcount > 0
        conn.commit()
        return inserted
