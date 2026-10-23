"""Nouvelle lecture des documents d'une source par leur identifiant natif (`staging.source_id`).

Chaque source implémente `StaleRefetch` (`pipeline/ingestion/<source>/fetch_stale.py`) : seule la requête par identifiant natif lui est propre. `refresh` fait la boucle commune.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping

import httpx2
from sqlalchemy import Connection, text

from domain.sources.registry import ALL_SOURCES_SET as VALID_SOURCES
from domain.types import JsonValue
from pipeline.http.circuit_breaker import source_tripped
from pipeline.http.fetch_pool import run_fetch_pool
from pipeline.http.lookup import UNAVAILABLE, LookupOutcome, NotFound, Unavailable
from pipeline.ingestion.common.staging import StagingStore, UpsertOutcome
from pipeline.runtime.observability.log_format import source_branch
from pipeline.runtime.observability.logging_scope import scoped_logger
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress

COMMIT_EVERY = 50


type FetchOutcome = LookupOutcome[Mapping[str, JsonValue]]
"""Document relu dans la source, ou son absence, ou l'indisponibilité de la source."""


class StaleRefetch(ABC):
    """Nouvelle lecture d'un document d'une source par son identifiant natif.

    Les sous-classes fixent `source_key`, `max_concurrent`, `request_delay_s` et implémentent `fetch_by_native_id`.
    """

    source_key: str
    max_concurrent: int  # plafond de requêtes simultanées, sous le rate-limit de l'API
    request_delay_s: float = 0.0  # pause par worker après chaque requête

    @abstractmethod
    async def fetch_by_native_id(
        self, client: httpx2.AsyncClient, source_id: str
    ) -> FetchOutcome: ...


# Filtre année (`{year_clause}`) : `publication_year` vient de `source_records` (LEFT JOIN ; NULL si absent, conservé).
_STALE_ROWS_SQL_TEMPLATE = """
    SELECT s.source_id
    FROM staging s
    LEFT JOIN source_records sr
      ON sr.source = s.source AND sr.source_id = s.source_id
    WHERE s.source = CAST(:source AS source_type)
      AND s.disappeared_at IS NULL
      AND s.last_seen_at < now() - make_interval(days => :days)
      {year_clause}
    ORDER BY s.id
"""

_SET_DISAPPEARED_SQL = text(
    """
    UPDATE staging SET disappeared_at = now()
    WHERE source = CAST(:source AS source_type) AND source_id = :source_id
      AND disappeared_at IS NULL
    """
)


def get_stale_source_ids(
    conn: Connection, source: str, years: list[int] | None = None, *, after_days: int
) -> list[str]:
    """Identifiants natifs des documents de `source` dont `last_seen_at` date de plus de `after_days` jours, hors documents disparus.

    `years` borne la sélection à la fenêtre d'années du run, jointe depuis `source_records.publication_year` : un run sur une période glissante relit seulement les documents de ses propres années. `None` = aucune borne.
    """
    if source not in VALID_SOURCES:
        raise ValueError(f"Source inconnue : {source}. Valides : {', '.join(VALID_SOURCES)}")
    params: dict[str, object] = {"source": source, "days": after_days}
    year_clause = ""
    if years is not None:
        year_clause = "AND (sr.publication_year IS NULL OR sr.publication_year = ANY(:years))"
        params["years"] = list(years)
    sql = text(_STALE_ROWS_SQL_TEMPLATE.format(year_clause=year_clause))
    return list(conn.execute(sql, params).scalars())


def set_disappeared(conn: Connection, source: str, source_id: str) -> None:
    """Pose `disappeared_at` sur le document `(source, source_id)` confirmé absent. Ne commite pas."""
    conn.execute(_SET_DISAPPEARED_SQL, {"source": source, "source_id": source_id})


async def refresh(
    conn: Connection,
    refetch: StaleRefetch,
    log: logging.Logger,
    *,
    after_days: int,
    years: list[int] | None = None,
) -> PhaseMetrics:
    """Relit par identifiant natif les documents de la source de `refetch` non revus depuis `after_days` jours.

    `years` borne la sélection à la fenêtre d'années du run (via `source_records.publication_year`) ; `None` = tous les documents anciens de la source.

    `updated` = `raw_data` réécrit (empreinte changée) ; `unchanged` = document identique (seul `last_seen_at` mis à jour) ; `errors` = source indisponible ; `extras["disappeared"]` = absences confirmées marquées `disappeared_at`.
    """
    source = refetch.source_key
    slog = scoped_logger(log, source)
    stale = get_stale_source_ids(conn, source, years, after_days=after_days)
    total = len(stale)

    metrics = PhaseMetrics(seen=total)
    if total == 0:
        return metrics

    processed = 0

    async def _fetch(client: httpx2.AsyncClient, source_id: str) -> FetchOutcome:
        try:
            outcome = await refetch.fetch_by_native_id(client, source_id)
        except Exception as e:
            # Breaker déclenché pendant la requête : abandon silencieux, le journal le signale une fois après le pool.
            if not source_tripped():
                slog.error("erreur sur %s : %s", source_id, e)
            outcome = UNAVAILABLE
        if refetch.request_delay_s:
            await asyncio.sleep(refetch.request_delay_s)
        return outcome

    with track_progress(total, source_branch(source), slog, count_kept=True) as progress:

        def _write(conn: Connection, source_id: str, outcome: FetchOutcome) -> None:
            nonlocal processed
            if isinstance(outcome, Unavailable):
                metrics.add(errors=1)
            elif isinstance(outcome, NotFound):
                set_disappeared(conn, source, source_id)
                metrics.add(disappeared=1)
            else:
                # La lecture par identifiant natif rend le document entier : aucun plafond d'auteurs.
                staged = StagingStore(conn).stage(source, outcome, listed=False)
                if staged is UpsertOutcome.UNCHANGED:
                    metrics.add(unchanged=1)
                elif staged is not None:
                    metrics.add(updated=1)
                progress.keep()
            processed += 1
            progress.advance()

        await run_fetch_pool(
            stale,
            conn,
            max_concurrent=refetch.max_concurrent,
            commit_every=COMMIT_EVERY,
            fetch=_fetch,
            write=_write,
        )

    return metrics
