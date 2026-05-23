"""Adapter OpenAlex pour la phase extract : HTTP (`/works` paginé par
cursor) + écritures staging + config.

Implémente le port
`application.ports.pipeline.extract.openalex.OpenalexExtractAdapter`.
L'orchestration de la phase (boucle par année, agrégation des métriques)
vit côté `application.pipeline.extract.extract_openalex`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract._common import BatchInsertCounts
from application.ports.pipeline.extract.openalex import (
    OpenalexExtractAdapter,
    OpenalexExtractConfig,
)
from domain.sources.openalex_extract import extract_doi, extract_openalex_id
from infrastructure.sources.api_limits import OPENALEX_PER_PAGE
from infrastructure.sources.common import compute_hash
from infrastructure.sources.config import (
    get_extraction_api_ids,
    get_openalex_api_key,
    get_polite_pool_email,
    get_years,
)
from infrastructure.sources.http_retry import http_request_with_retry
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params, init_auth

_INSERT_OA_BATCH_SQL = text(
    """
    INSERT INTO staging (source, source_id, doi, raw_data, raw_hash)
    VALUES ('openalex', :source_id, :doi, :raw_data, :raw_hash)
    ON CONFLICT (source, source_id) DO UPDATE SET
        raw_data = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN EXCLUDED.raw_data
            ELSE staging.raw_data
        END,
        raw_hash = COALESCE(EXCLUDED.raw_hash, staging.raw_hash),
        processed = CASE
            WHEN staging.raw_hash IS DISTINCT FROM EXCLUDED.raw_hash
                THEN FALSE
            ELSE staging.processed
        END,
        last_seen_at = now()
    RETURNING (xmax = 0) AS inserted
    """
).bindparams(bindparam("raw_data", type_=JSONB))


def build_params(
    institution_ids: list[str],
    *,
    year: int | None = None,
    cursor: str = "*",
    since: str | None = None,
) -> dict[str, Any]:
    """Construit les paramètres de requête pour l'API OpenAlex `/works`.

    Si `since` est fourni (format `YYYY-MM-DD`), filtre sur
    `from_updated_date`. Sinon filtre sur `publication_year`. Le
    `lineage:` agrège les institutions par `|` (OR).
    """
    lineage_filter = "|".join(institution_ids or [])
    if since:
        filter_str = f"authorships.institutions.lineage:{lineage_filter},from_updated_date:{since}"
    else:
        filter_str = f"authorships.institutions.lineage:{lineage_filter},publication_year:{year}"
    return {
        "filter": filter_str,
        "select": SELECT_FIELDS,
        "per_page": OPENALEX_PER_PAGE,
        "cursor": cursor,
        **auth_params(),
    }


class PgOpenalexExtractAdapter(OpenalexExtractAdapter):
    """Adapter PostgreSQL + HTTP pour `OpenalexExtractAdapter`.

    Construit avec une `base_url` (endpoint `/works`). L'auth (api_key
    ou email polite pool) est initialisée via `init_auth(...)` lors du
    `load_config` — état global du module `infrastructure.sources.openalex`
    partagé avec `refetch_truncated` et `fetch_missing_doi`.
    """

    def __init__(self, base_url: str) -> None:
        self._url = base_url

    # ── Config ─────────────────────────────────────────────────

    def load_config(self, conn: Connection) -> OpenalexExtractConfig:
        institution_ids = get_extraction_api_ids(conn, "openalex")
        init_auth(api_key=get_openalex_api_key(conn), email=get_polite_pool_email(conn))
        return OpenalexExtractConfig(
            base_url=self._url,
            institution_ids=institution_ids,
        )

    def get_years(self, conn: Connection, *, mode: str) -> list[int]:
        return get_years(conn, mode=mode)

    # ── HTTP ───────────────────────────────────────────────────

    def fetch_page(
        self,
        institution_ids: list[str],
        *,
        year: int | None = None,
        cursor: str = "*",
        since: str | None = None,
    ) -> dict[str, Any]:
        params = build_params(institution_ids, year=year, cursor=cursor, since=since)
        label = f"OpenAlex {since or year}"
        return http_request_with_retry("GET", self._url, params=params, timeout=30, label=label)

    # ── SQL ────────────────────────────────────────────────────

    def insert_batch(self, conn: Connection, works: list[dict[str, Any]]) -> BatchInsertCounts:
        """UPSERT bulk d'un batch de works, ventilé new/updated via `xmax`.

        `raw_hash` est l'unique clé de détection de changement, aligné sur
        le pattern des autres sources. La préservation des authorships
        complètes obtenues par `refetch_truncated` repose sur le fait que
        **refetch ne recalcule pas `raw_hash`** : la ligne refetchée garde
        le hash du payload bulk initial. Tant que le bulk renvoie ce même
        payload, la comparaison `raw_hash` reste équivalente et l'UPSERT
        ne touche pas `raw_data`.

        Le caller est responsable du `conn.commit()` après cette méthode.

        Sémantique des compteurs : `new` = vraies insertions (`xmax = 0`),
        `updated` = ON CONFLICT déclenchés (même si le `CASE WHEN` n'a
        finalement rien modifié — sémantique « row touchée »).
        """
        if not works:
            return BatchInsertCounts(new=0, updated=0)

        batch = [
            {
                "source_id": extract_openalex_id(work),
                "doi": extract_doi(work),
                "raw_data": work,
                "raw_hash": compute_hash(work),
            }
            for work in works
        ]
        result = conn.execute(_INSERT_OA_BATCH_SQL, batch)
        rows = result.all()
        new_count = sum(1 for r in rows if r.inserted)
        return BatchInsertCounts(new=new_count, updated=len(rows) - new_count)
