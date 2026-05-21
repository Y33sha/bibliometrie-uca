"""Query service pour les snapshots de runs pipeline (table `pipeline_run_snapshots`).

Adapter SA pour le port `application.ports.api.pipeline_runs_queries.PipelineRunsQueries`.
"""

from __future__ import annotations

import logging
from typing import cast

from sqlalchemy import Connection, text

from application.ports.api.pipeline_runs_queries import (
    PipelineRunDetail,
    PipelineRunsQueries,
    PipelineRunSummary,
)
from application.ports.pipeline.runs import RunSnapshotPayload

logger = logging.getLogger(__name__)


class PgPipelineRunsQueries(PipelineRunsQueries):
    """Adapter SA pour `PipelineRunsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_recent(self, limit: int = 50) -> list[PipelineRunSummary]:
        """N derniers snapshots, plus récent en premier.

        Lit uniquement les champs résumés depuis le payload JSONB (extraction
        SQL pour éviter de désérialiser le payload entier).
        """
        rows = self._conn.execute(
            text(
                """
                SELECT
                    id,
                    ran_at,
                    mode,
                    COALESCE((payload ->> 'total_duration_s')::float, 0.0) AS total_duration_s,
                    COALESCE(payload -> 'sources', '[]'::jsonb) AS sources,
                    COALESCE(payload -> 'phases_run', '[]'::jsonb) AS phases_run
                FROM pipeline_run_snapshots
                ORDER BY ran_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).all()
        return [
            PipelineRunSummary(
                id=r.id,
                ran_at=r.ran_at,
                mode=r.mode,
                total_duration_s=r.total_duration_s,
                sources=list(r.sources),
                phases_run=list(r.phases_run),
            )
            for r in rows
        ]

    def get_by_id(self, run_id: int) -> PipelineRunDetail | None:
        """Détail d'un run par id (payload JSONB complet)."""
        row = self._conn.execute(
            text("SELECT id, ran_at, mode, payload FROM pipeline_run_snapshots WHERE id = :id"),
            {"id": run_id},
        ).first()
        if row is None:
            return None
        return PipelineRunDetail(
            id=row.id,
            ran_at=row.ran_at,
            mode=row.mode,
            payload=cast(RunSnapshotPayload, row.payload),
        )
