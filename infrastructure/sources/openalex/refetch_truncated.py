"""Adapter OpenAlex pour `application.pipeline.extract.refetch_truncated`.

HTTP (un appel par work) + SELECT (works marqués `staging.authors_truncated`) +
UPDATE staging.raw_data (efface le flag, sans recalcul de raw_hash).

L'orchestration (boucle async, sémaphore, commits intermédiaires) vit
côté `application.pipeline.extract.refetch_truncated`.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.extract.refetch_truncated import (
    OpenalexRefetchAdapter,
    TruncatedWork,
)
from infrastructure.sources.config import (
    get_api_base_urls,
    get_openalex_api_key,
    get_polite_pool_email,
)
from infrastructure.sources.http_retry_async import http_request_with_retry_async
from infrastructure.sources.openalex import SELECT_FIELDS, auth_params, init_auth

MAX_CONCURRENT = 3

# Le refetch ne recalcule **pas** `raw_hash` : la ligne garde le hash du
# payload bulk initial. Cette dissymétrie volontaire est le mécanisme de
# préservation (cf. orchestrateur). Tant que le bulk renvoie le même
# payload tronqué, son hash matchera celui en base et l'UPSERT bulk ne
# touchera pas `raw_data` (qui contient pourtant les auteurs complets).
# Efface `authors_truncated` (le work est désormais complet et vérifié) et
# repasse `processed = FALSE` pour que normalize ré-écrive les authorships complètes.
_UPDATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, processed = FALSE, authors_truncated = FALSE, last_seen_at = now()
    WHERE id = :id
    """
).bindparams(bindparam("raw_data", type_=JSONB))

# Genuine 100 auteurs : pas tronqué, on lève juste le drapeau (pas de réécriture).
_CLEAR_TRUNCATED_SQL = text("UPDATE staging SET authors_truncated = FALSE WHERE id = :id")

# Détection par le marqueur explicite posé à l'extraction : indépendant de l'ordre
# des phases (survit à normalize, qui purge `raw_data`) et de la source des auteurs.
# `source_id` (l'ID OpenAlex) reste sur la ligne staging même après purge du brut.
_SELECT_TRUNCATED_SQL = text(
    """
    SELECT id, source_id
    FROM staging
    WHERE source = 'openalex' AND authors_truncated
    ORDER BY id
    """
)


class PgOpenalexRefetchAdapter(OpenalexRefetchAdapter):
    """Adapter PostgreSQL + HTTP pour `OpenalexRefetchAdapter`.

    `base_url` est résolu lors de `configure()` (depuis la BDD), au
    même endroit que `init_auth()` — la connexion DB est nécessaire
    aux deux et l'orchestrateur la passe déjà.
    """

    max_concurrent: int = MAX_CONCURRENT

    def __init__(self) -> None:
        self._base_url: str = ""

    def configure(self, conn: Connection) -> None:
        init_auth(api_key=get_openalex_api_key(conn), email=get_polite_pool_email(conn))
        self._base_url = get_api_base_urls()["openalex"]

    def find_truncated(self, conn: Connection, *, limit: int | None = None) -> list[TruncatedWork]:
        rows = conn.execute(_SELECT_TRUNCATED_SQL).all()
        if limit:
            rows = rows[:limit]
        return [TruncatedWork(staging_id=row.id, openalex_id=row.source_id) for row in rows]

    async def fetch_work(
        self, client: httpx.AsyncClient, openalex_id: str
    ) -> dict[str, Any] | None:
        """Fetch un work individuel par son ID OpenAlex (retourne tous les auteurs).

        Retourne le dict ou None si l'API renvoie 404 ou si la requête
        a échoué après tous les retries.
        """
        url = f"{self._base_url}/{openalex_id}"
        params = {"select": SELECT_FIELDS, **auth_params()}
        try:
            return await http_request_with_retry_async(
                client, "GET", url, params=params, timeout=30, label=f"OA {openalex_id}"
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                # On laisse l'orchestrateur logger ; on remonte juste None.
                return None
            return None
        except httpx.RequestError:
            return None

    def update_raw_data(self, conn: Connection, staging_id: int, work: dict[str, Any]) -> None:
        conn.execute(_UPDATE_SQL, {"raw_data": work, "id": staging_id})

    def clear_truncated(self, conn: Connection, staging_id: int) -> None:
        conn.execute(_CLEAR_TRUNCATED_SQL, {"id": staging_id})
