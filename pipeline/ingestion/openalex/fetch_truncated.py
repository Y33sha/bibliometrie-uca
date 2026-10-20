"""Phase `fetch_truncated` : nouvelle lecture des works OpenAlex dont la liste d'auteurs est peut-être tronquée. Tâche `fetch_truncated.refetch_openalex`.

Une réponse de liste d'OpenAlex plafonne les auteurs d'un work à `BULK_AUTHORSHIPS_CAP`. Le moissonnage marque `staging.authors_truncated` les works qui atteignent ce plafond ; cette phase les relit un par un par `/works/{id}`, qui rend tous les auteurs.

**Préservation des auteurs complets.** La nouvelle lecture ne recalcule **pas** `raw_hash` : la ligne garde l'empreinte du work moissonné. Tant que le moissonnage rend le même work tronqué, son empreinte égale celle en base et l'écriture laisse `raw_data` en place. Un work modifié dans OpenAlex écrase `raw_data` par sa version tronquée, de nouveau marquée : cette phase la relit au même run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass

import httpx2
from sqlalchemy import Connection, bindparam, text

from domain.types import JsonValue, as_sequence
from infrastructure.db.jsonb import Jsonb
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.http.lookup import LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.openalex.api import fetch_work
from pipeline.ingestion.openalex.payload import BULK_AUTHORSHIPS_CAP
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.libelles import DERNIERE_BRANCHE, accord, etape, forme
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progression import progression
from pipeline.task_runner import SingleTaskPhase

COMMIT_EVERY = 50
# Plafond OpenAlex 10 req/s.
MAX_CONCURRENT = 3

# Le marqueur posé au moissonnage survit à la normalisation, qui vide `raw_data` : la sélection ne dépend ni de l'ordre des phases ni du comptage des auteurs.
_SELECT_TRUNCATED_SQL = text(
    """
    SELECT id, source_id
    FROM staging
    WHERE source = 'openalex' AND authors_truncated
    ORDER BY id
    """
)

# Réécrit `raw_data` sans recalculer `raw_hash` (cf. docstring du module), lève le marqueur et repasse `processed = FALSE` : la normalisation réécrit les signatures complètes.
_UPDATE_SQL = text(
    """
    UPDATE staging
    SET raw_data = :raw_data, processed = FALSE, authors_truncated = FALSE, last_seen_at = now()
    WHERE id = :id
    """
).bindparams(bindparam("raw_data", type_=Jsonb))

_CLEAR_TRUNCATED_SQL = text("UPDATE staging SET authors_truncated = FALSE WHERE id = :id")


@dataclass(frozen=True, slots=True)
class TruncatedWork:
    """Work de `staging` soupçonné d'être tronqué."""

    staging_id: int
    openalex_id: str


@dataclass(frozen=True)
class FetchTruncatedPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Relit les works tronqués dans une transaction, dès qu'OpenAlex fait partie des sources du run. La phase tourne dans tous les modes."""
        if "openalex" not in ctx.options.sources:
            return PhaseMetrics()
        with ctx.open_tx() as conn:
            return asyncio.run(refetch_openalex(conn, ctx.logger))


async def refetch_openalex(conn: Connection, log: logging.Logger) -> PhaseMetrics:
    """Relit les works OpenAlex marqués `staging.authors_truncated`.

    `updated` = works réécrits ; `extras["already_complete"]` = works qui avaient exactement le plafond d'auteurs (marqueur levé) ; `extras["not_found"]` = works qu'OpenAlex ne connaît plus (marqueur levé) ; `errors` = OpenAlex indisponible (marqueur conservé).
    """
    truncated = [
        TruncatedWork(staging_id=row.id, openalex_id=row.source_id)
        for row in conn.execute(_SELECT_TRUNCATED_SQL)
    ]
    total = len(truncated)

    metrics = PhaseMetrics(seen=total)
    if not truncated:
        return metrics

    etape(
        log,
        "%s de %d auteurs, potentiellement %s",
        accord(total, "document"),
        BULK_AUTHORSHIPS_CAP,
        forme(total, "tronqué"),
    )

    async def _fetch(
        client: httpx2.AsyncClient, ref: TruncatedWork
    ) -> LookupOutcome[Mapping[str, JsonValue]]:
        return await fetch_work(client, ref.openalex_id)

    with progression(total, DERNIERE_BRANCHE.rstrip(), log) as avancement:

        def _write(
            conn: Connection, ref: TruncatedWork, work: LookupOutcome[Mapping[str, JsonValue]]
        ) -> None:
            if isinstance(work, Unavailable):
                metrics.add(errors=1)
            elif isinstance(work, NotFound):
                conn.execute(_CLEAR_TRUNCATED_SQL, {"id": ref.staging_id})
                metrics.add(not_found=1)
            elif len(as_sequence(work.get("authorships"))) <= BULK_AUTHORSHIPS_CAP:
                # Work complet au plafond près : le marqueur est levé, sans réécrire `raw_data` ni relancer la normalisation.
                conn.execute(_CLEAR_TRUNCATED_SQL, {"id": ref.staging_id})
                metrics.add(already_complete=1)
            else:
                conn.execute(_UPDATE_SQL, {"raw_data": work, "id": ref.staging_id})
                metrics.add(updated=1)
            avancement.avance()

        await run_fetch_pool(
            truncated,
            conn,
            max_concurrent=MAX_CONCURRENT,
            commit_every=COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
        )

    return metrics


# ── Câblage ───────────────────────────────────────────────────


def build() -> Phase:
    return SingleTaskPhase("fetch_truncated.refetch_openalex", FetchTruncatedPhase(), label="Bilan")
