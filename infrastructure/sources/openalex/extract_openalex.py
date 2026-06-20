"""Adapter OpenAlex pour la phase extract : HTTP (`/works` paginé par
cursor) + écritures staging + config.

Implémente le port
`application.ports.pipeline.extract.openalex.OpenalexExtractAdapter`.
L'orchestration de la phase (boucle par année, agrégation des métriques)
vit côté `application.pipeline.extract.extract_openalex`.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import Connection

from application.ports.pipeline.extract._common import BatchInsertCounts
from application.ports.pipeline.extract.openalex import (
    OpenalexExtractAdapter,
    OpenalexExtractConfig,
)
from infrastructure.sources.api_limits import OPENALEX_DELAY, OPENALEX_PER_PAGE
from infrastructure.sources.common import upsert_staging
from infrastructure.sources.config import (
    get_extraction_api_ids,
    get_openalex_api_key,
    get_polite_pool_email,
    get_years,
)
from infrastructure.sources.http_retry import http_request_with_retry
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params, init_auth
from infrastructure.sources.openalex.parsing import extract_doi, extract_openalex_id


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
        self._last_request_at: float | None = None

    def _get(self, params: dict[str, Any], label: str) -> dict[str, Any]:
        """GET `/works`, auto rate-limité : au moins `OPENALEX_DELAY` entre deux appels.

        L'adapter se rate-limite seul, quel que soit l'appelant — l'orchestrateur
        n'ordonnance aucun `sleep`. On mesure l'écart depuis la dernière requête au
        lieu de dormir systématiquement après coup : le temps de traitement entre
        deux pages (insert batch, commit) est déjà décompté du délai.
        """
        if self._last_request_at is not None:
            wait = OPENALEX_DELAY - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        try:
            return http_request_with_retry("GET", self._url, params=params, timeout=30, label=label)
        finally:
            self._last_request_at = time.monotonic()

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

    # ── Parsing (pur, sans I/O) ────────────────────────────────

    def extract_id(self, work: dict[str, Any]) -> str:
        """Extrait l'ID OpenAlex court (`W...`) d'un work (cf. `parsing`)."""
        return extract_openalex_id(work)

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
        return self._get(params, label)

    # ── SQL ────────────────────────────────────────────────────

    def insert_batch(self, conn: Connection, works: list[dict[str, Any]]) -> BatchInsertCounts:
        """UPSERT bulk d'un batch de works, ventilé new/updated/unchanged.

        La préservation des authorships complètes obtenues par `refetch_truncated`
        repose sur le fait que **refetch ne recalcule pas `raw_hash`** : la ligne
        refetchée garde le hash du payload bulk initial. Tant que le bulk renvoie ce
        même payload, la comparaison `raw_hash` reste équivalente et l'UPSERT ne touche
        pas `raw_data`.

        Le caller est responsable du `conn.commit()` après cette méthode.

        Sémantique des compteurs : `new` = vraies insertions (`xmax = 0`), `updated` =
        contenu réécrit (hash changé), `unchanged` = re-vu à hash identique (seul
        `last_seen_at` bumpé).
        """
        new_count = 0
        updated_count = 0
        unchanged_count = 0
        for work in works:
            inserted, changed = upsert_staging(
                conn,
                source="openalex",
                source_id=extract_openalex_id(work),
                doi=extract_doi(work),
                raw_data=work,
            )
            if inserted:
                new_count += 1
            elif changed:
                updated_count += 1
            else:
                unchanged_count += 1
        return BatchInsertCounts(new=new_count, updated=updated_count, unchanged=unchanged_count)
