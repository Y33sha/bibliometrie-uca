"""Query service pour les exécutions de phase (table `pipeline_phase_executions`).

Adapter SA pour le port `PhaseExecutionsQueries`. Le rendement et l'écart de durée
sont recalculés à la lecture via `application.observability.read` ; le médian
historique de durée se calcule sur les exécutions réussies de la même phase, hors
run courant.
"""

from __future__ import annotations

from collections import defaultdict
from typing import cast

from sqlalchemy import Connection, text

from application.observability.read import compute_yield, duration_ratio, median_duration
from application.ports.api.pipeline_phase_executions_queries import (
    PhaseBrief,
    PhaseExecutionDetail,
    PhaseExecutionsQueries,
    RunDetail,
    RunSummary,
)
from application.ports.pipeline.phase_executions import (
    ObservableVolumes,
    PhaseExecution,
    PhaseMetricsPayload,
    PhaseStatus,
    Signal,
)


class PgPhaseExecutionsQueries(PhaseExecutionsQueries):
    """Adapter SA pour `PhaseExecutionsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_runs(self, limit: int = 50) -> list[RunSummary]:
        """N derniers runs, plus récent en premier. Statut global = le pire des
        statuts de phase ; mode et sources pris sur la première phase du run."""
        rows = self._conn.execute(
            text(
                """
                WITH agg AS (
                    SELECT run_id,
                           min(started_at) AS started_at,
                           max(ended_at) AS ended_at,
                           count(*) AS phase_count,
                           CASE WHEN bool_or(status = 'error') THEN 'error'
                                WHEN bool_or(status = 'warning') THEN 'warning'
                                ELSE 'ok' END AS status,
                           sum((metrics ->> 'duration_s')::float) AS total_duration_s,
                           jsonb_agg(
                               jsonb_build_object('phase', phase, 'status', status)
                               ORDER BY id
                           ) AS phases
                    FROM pipeline_phase_executions
                    GROUP BY run_id
                )
                SELECT a.run_id, a.started_at, a.ended_at, a.phase_count, a.status,
                       a.total_duration_s, a.phases, r.mode, r.sources
                FROM agg a
                JOIN LATERAL (
                    SELECT mode, sources FROM pipeline_phase_executions p
                    WHERE p.run_id = a.run_id ORDER BY id LIMIT 1
                ) r ON true
                ORDER BY a.run_id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).all()
        return [
            RunSummary(
                run_id=r.run_id,
                started_at=r.started_at,
                ended_at=r.ended_at,
                mode=r.mode,
                sources=list(r.sources),
                status=cast(PhaseStatus, r.status),
                phase_count=r.phase_count,
                total_duration_s=r.total_duration_s,
                phases=[PhaseBrief(phase=p["phase"], status=p["status"]) for p in r.phases],
            )
            for r in rows
        ]

    def get_run(self, run_id: int) -> RunDetail | None:
        """Détail d'un run : ses phases dans l'ordre d'exécution, rendement et écart
        de durée recalculés."""
        rows = self._conn.execute(
            text(
                """
                SELECT phase, started_at, ended_at, mode, sources, status,
                       signals, metrics, input, output
                FROM pipeline_phase_executions
                WHERE run_id = :run_id
                ORDER BY id
                """
            ),
            {"run_id": run_id},
        ).all()
        if not rows:
            return None

        history = self._historical_durations(run_id, [r.phase for r in rows])
        phases: list[PhaseExecutionDetail] = []
        for r in rows:
            metrics = cast(PhaseMetricsPayload, r.metrics)
            execution = PhaseExecution(
                run_id=run_id,
                phase=r.phase,
                started_at=r.started_at,
                ended_at=r.ended_at,
                mode=r.mode,
                sources=list(r.sources),
                status=cast(PhaseStatus, r.status),
                metrics=metrics,
                signals=cast("list[Signal]", r.signals),
                input=cast("ObservableVolumes | None", r.input),
                output=cast("ObservableVolumes | None", r.output),
            )
            duration_s = float(metrics["duration_s"])
            median = median_duration(history.get(r.phase, []))
            phases.append(
                PhaseExecutionDetail(
                    phase=r.phase,
                    started_at=r.started_at,
                    ended_at=r.ended_at,
                    status=execution.status,
                    duration_s=duration_s,
                    metrics=metrics,
                    input=execution.input,
                    output=execution.output,
                    yield_ratio=compute_yield(execution),
                    historical_median_duration_s=median,
                    duration_ratio=duration_ratio(duration_s, median),
                    signals=execution.signals,
                )
            )

        status: PhaseStatus = (
            "error"
            if any(p.status == "error" for p in phases)
            else "warning"
            if any(p.status == "warning" for p in phases)
            else "ok"
        )
        return RunDetail(
            run_id=run_id,
            started_at=min(p.started_at for p in phases),
            ended_at=max(p.ended_at for p in phases),
            mode=rows[0].mode,
            sources=list(rows[0].sources),
            status=status,
            total_duration_s=sum(p.duration_s for p in phases),
            phases=phases,
        )

    def _historical_durations(self, run_id: int, phases: list[str]) -> dict[str, list[float]]:
        """Durées des exécutions réussies des mêmes phases, hors run courant."""
        rows = self._conn.execute(
            text(
                """
                SELECT phase, (metrics ->> 'duration_s')::float AS duration_s
                FROM pipeline_phase_executions
                WHERE status = 'ok' AND run_id <> :run_id AND phase = ANY(:phases)
                """
            ),
            {"run_id": run_id, "phases": phases},
        ).all()
        history: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            history[r.phase].append(r.duration_s)
        return dict(history)
