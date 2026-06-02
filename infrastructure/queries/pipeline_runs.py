"""Query service pour les snapshots de runs pipeline (table `pipeline_run_snapshots`).

Adapter SA pour le port `application.ports.api.pipeline_runs_queries.PipelineRunsQueries`.
"""

from __future__ import annotations

import logging
from typing import cast

from sqlalchemy import Connection, text

from application.ports.api.pipeline_runs_queries import (
    PipelineRunDetail,
    PipelineRunObservation,
    PipelineRunsQueries,
    PipelineRunSummary,
)
from application.ports.pipeline.runs import RunSnapshotPayload
from infrastructure.observability.pipeline_runs import (
    build_observations,
    fetch_previous_observables,
)

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
        """Détail d'un run par id : payload complet + observations recalculées.

        Les observations sont reconstruites en comparant les observables courants
        à ceux du snapshot précédent du même mode (recalcul à la lecture pour
        rester à jour si les seuils évoluent).
        """
        row = self._conn.execute(
            text("SELECT id, ran_at, mode, payload FROM pipeline_run_snapshots WHERE id = :id"),
            {"id": run_id},
        ).first()
        if row is None:
            return None
        # Snapshots antérieurs au split du compteur extract n'ont pas `unchanged`
        # dans leurs métriques par phase : on le défaute à 0 à la lecture (la
        # colonne du TypedDict reste requise pour les snapshots à venir).
        for pm in row.payload.get("metrics_per_phase", {}).values():
            pm.setdefault("unchanged", 0)
        payload = cast(RunSnapshotPayload, row.payload)
        previous_observables = fetch_previous_observables(
            self._conn, mode=row.mode, before_ran_at=row.ran_at
        )
        previous_at_row = self._conn.execute(
            text(
                "SELECT ran_at FROM pipeline_run_snapshots "
                "WHERE mode = :mode AND ran_at < :before "
                "ORDER BY ran_at DESC LIMIT 1"
            ),
            {"mode": row.mode, "before": row.ran_at},
        ).first()
        observations = [
            PipelineRunObservation(
                key=o.key,
                label=o.label,
                current=o.current,
                previous=o.previous,
                delta_pct=o.delta_pct,
                suspect=o.suspect,
                threshold_note=o.threshold_note,
            )
            for o in build_observations(payload["observables"], previous_observables)
        ]
        return PipelineRunDetail(
            id=row.id,
            ran_at=row.ran_at,
            previous_snapshot_at=previous_at_row.ran_at if previous_at_row else None,
            mode=row.mode,
            payload=payload,
            observations=observations,
        )
