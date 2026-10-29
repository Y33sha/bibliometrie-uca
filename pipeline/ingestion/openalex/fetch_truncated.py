"""Phase `fetch_truncated` : nouvelle lecture des works OpenAlex dont la liste d'auteurs est peut-être tronquée. Tâche `fetch_truncated.refetch_openalex`.

Une réponse de liste d'OpenAlex plafonne les auteurs d'un work à `BULK_AUTHORSHIPS_CAP`. Le moissonnage marque `staging.authors_truncated` les works qui atteignent ce plafond ; cette phase les relit un par un par `/works/{id}`, qui rend tous les auteurs.

La nouvelle lecture garde l'empreinte du work moissonné (`StagingStore.complete_authors`). Tant que le moissonnage rend le même work tronqué, son empreinte égale celle en base, et l'écriture laisse les auteurs complets en place. Un work modifié dans OpenAlex écrase le contenu par sa version tronquée, de nouveau marquée : cette phase la relit au même run.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import Connection, text

from domain.types import JsonValue, as_sequence
from pipeline.ingestion.common.lookup import LookupChannel, look_up, one_at_a_time
from pipeline.ingestion.common.staging import StagingStore, UpsertOutcome
from pipeline.ingestion.openalex.api import fetch_work
from pipeline.ingestion.openalex.fields import extract_openalex_id
from pipeline.ingestion.openalex.payload import BULK_AUTHORSHIPS_CAP
from pipeline.runtime.context import Phase, PhaseContext
from pipeline.runtime.observability.log_format import inflect, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.task_runner import SingleTaskPhase

# Plafond OpenAlex 10 req/s.
MAX_CONCURRENT = 3

# Le marqueur posé au moissonnage survit à la normalisation, qui vide `raw_data` : la sélection ne dépend ni de l'ordre des phases ni du comptage des auteurs.
_SELECT_TRUNCATED_SQL = text(
    """
    SELECT source_id
    FROM staging
    WHERE source = 'openalex' AND authors_truncated
    ORDER BY id
    """
)


@dataclass(frozen=True)
class FetchTruncatedPhase:
    def run(self, ctx: PhaseContext) -> PhaseMetrics:
        """Relit les works tronqués dans une transaction, dès qu'OpenAlex fait partie des sources du run. La phase tourne dans tous les modes."""
        if "openalex" not in ctx.options.sources:
            return PhaseMetrics()
        with ctx.open_tx() as conn:
            return asyncio.run(refetch_openalex(conn, ctx.logger))


def _complete(staging: StagingStore, work: Mapping[str, JsonValue]) -> UpsertOutcome | None:
    """Écrit le work complet. Un work qui compte au plus le plafond d'auteurs était complet : son marqueur est levé, sans réécrire `raw_data` ni relancer la normalisation."""
    if len(as_sequence(work.get("authorships"))) > BULK_AUTHORSHIPS_CAP:
        return staging.complete_authors("openalex", work)
    staging.clear_truncated("openalex", extract_openalex_id(work))
    return UpsertOutcome.UNCHANGED


async def refetch_openalex(conn: Connection, log: logging.Logger) -> PhaseMetrics:
    """Relit les works OpenAlex marqués tronqués (`staging.authors_truncated`).

    Rend les compteurs de `look_up` : works réécrits (`updated`), works qui avaient exactement le plafond d'auteurs (`unchanged`), works inconnus d'OpenAlex (`not_found`), lots non servis (`errors`). Le marqueur est levé, sauf pour les lots non servis.
    """
    truncated = list(conn.execute(_SELECT_TRUNCATED_SQL).scalars())
    if not truncated:
        return PhaseMetrics()
    step(
        log,
        "%s de %d auteurs, potentiellement %s",
        quantity(len(truncated), "document"),
        BULK_AUTHORSHIPS_CAP,
        inflect(len(truncated), "tronqué"),
    )
    return await look_up(
        conn,
        log,
        LookupChannel(
            source="openalex",
            fetch=one_at_a_time(fetch_work),
            on_absent=lambda conn, openalex_id: StagingStore(conn).clear_truncated(
                "openalex", openalex_id
            ),
            stage=_complete,
            max_concurrent=MAX_CONCURRENT,
        ),
        truncated,
    )


def build() -> Phase:
    return SingleTaskPhase("fetch_truncated.refetch_openalex", FetchTruncatedPhase(), label="Bilan")
