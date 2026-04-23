"""Adapter OpenAlex pour `application.pipeline.fetch_missing_doi`.

Un appel par DOI sur le filtre `doi:...` de l'API Works.
"""

from __future__ import annotations

from typing import Any, Iterable

import requests
from psycopg.types.json import Jsonb as Json

from infrastructure.api_limits import OPENALEX_DELAY
from infrastructure.app_config import get_api_base_urls, get_openalex_api_key, get_openalex_email
from infrastructure.sources.common import compute_hash
from infrastructure.sources.openalex import (
    SELECT_FIELDS,
    auth_params,
    extract_doi,
    extract_openalex_id,
    init_auth,
)


class OpenalexFetchMissingDoiAdapter:
    source_key = "openalex"
    rate_delay = OPENALEX_DELAY
    batch_size = 1

    base_url: str

    def configure(self, cur: Any) -> None:
        init_auth(api_key=get_openalex_api_key(cur), email=get_openalex_email(cur))
        self.base_url = get_api_base_urls(cur)["openalex"]

    def fetch(self, dois: list[str]) -> Iterable[dict]:
        doi = dois[0]
        params = {
            "filter": f"doi:{doi}",
            "select": SELECT_FIELDS,
            **auth_params(),
        }
        try:
            resp = requests.get(self.base_url, params=params, timeout=30)
            resp.raise_for_status()
        except requests.RequestException:
            return []
        return resp.json().get("results", [])[:1]

    def insert(self, conn: Any, record: dict) -> bool:
        oa_id = extract_openalex_id(record)
        doi = extract_doi(record)
        raw_hash = compute_hash(record)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, processed)
                VALUES ('openalex', %s, %s, %s::jsonb, %s, FALSE)
                ON CONFLICT (source, source_id) DO NOTHING
                """,
                (oa_id, doi, Json(record), raw_hash),
            )
            inserted = cur.rowcount > 0
        conn.commit()
        return inserted
