"""Adapter OpenAlex pour `application.pipeline.fetch_truncated.phase`.

HTTP (un appel par work) + SELECT (works marqués `staging.authors_truncated`) + UPDATE staging.raw_data (efface le flag, sans recalcul de raw_hash).

L'orchestration (boucle async, sémaphore, commits intermédiaires) vit côté `application.pipeline.fetch_truncated.phase`.
"""

from __future__ import annotations

from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection, bindparam, text

from application.ports.pipeline.fetch_truncated import (
    OpenalexFetchTruncatedAdapter,
    TruncatedWork,
)
from application.ports.pipeline.lookup import LookupOutcome, NotFound, Unavailable
from domain.types import JsonValue, as_mapping
from infrastructure.db.jsonb import Jsonb
from infrastructure.sources.api_params import API_BASE_URLS
from infrastructure.sources.http_retry import lookup_json_async
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params

MAX_CONCURRENT = 3

# Le refetch ne recalcule **pas** `raw_hash` : la ligne garde le hash du
# payload bulk initial. Cette dissymétrie volontaire est le mécanisme de
# préservation (cf. orchestrateur). Tant que le bulk renvoie le même
# payload tronqué, son hash matchera celui en base et l'UPSERT bulk ne
# touchera pas `raw_data` (qui contient pourtant les auteurs complets).
# Efface `authors_truncated` (le work est complet et vérifié) et
# repasse `processed = FALSE` pour que normalize ré-écrive les authorships complètes.
_UPDATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, processed = FALSE, authors_truncated = FALSE, last_seen_at = now()
    WHERE id = :id
    """
).bindparams(bindparam("raw_data", type_=Jsonb))

# Genuine 100 auteurs : pas tronqué, on lève juste le drapeau (pas de réécriture).
_CLEAR_TRUNCATED_SQL = text("UPDATE staging SET authors_truncated = FALSE WHERE id = :id")

# Détection par le marqueur explicite posé à l'extraction : indépendant de l'ordre des phases (survit à normalize, qui purge `raw_data`) et de la source des auteurs. `source_id` (l'ID OpenAlex) reste sur la ligne staging même après purge du brut.
_SELECT_TRUNCATED_SQL = text(
    """
    SELECT id, source_id
    FROM staging
    WHERE source = 'openalex' AND authors_truncated
    ORDER BY id
    """
)


class PgOpenalexFetchTruncatedAdapter(OpenalexFetchTruncatedAdapter):
    """Adapter PostgreSQL + HTTP pour `OpenalexFetchTruncatedAdapter`.

    `base_url` est résolu lors de `configure()`.
    """

    max_concurrent: int = MAX_CONCURRENT

    def __init__(self) -> None:
        self._base_url: str = ""

    def configure(self, conn: Connection) -> None:
        self._base_url = API_BASE_URLS["openalex"]

    def find_truncated(self, conn: Connection, *, limit: int | None = None) -> list[TruncatedWork]:
        rows = conn.execute(_SELECT_TRUNCATED_SQL).all()
        if limit:
            rows = rows[:limit]
        return [TruncatedWork(staging_id=row.id, openalex_id=row.source_id) for row in rows]

    async def fetch_work(
        self, client: httpx2.AsyncClient, openalex_id: str
    ) -> LookupOutcome[Mapping[str, JsonValue]]:
        """Fetch un work individuel par son ID OpenAlex (retourne tous les auteurs)."""
        outcome = await lookup_json_async(
            client,
            "GET",
            f"{self._base_url}/{openalex_id}",
            params={"select": SELECT_FIELDS, **auth_params()},
            timeout=30,
            label=f"OA {openalex_id}",
        )
        if isinstance(outcome, NotFound | Unavailable):
            return outcome
        return as_mapping(outcome)

    def update_raw_data(
        self, conn: Connection, staging_id: int, work: Mapping[str, JsonValue]
    ) -> None:
        conn.execute(_UPDATE_SQL, {"raw_data": work, "id": staging_id})

    def clear_truncated(self, conn: Connection, staging_id: int) -> None:
        conn.execute(_CLEAR_TRUNCATED_SQL, {"id": staging_id})
