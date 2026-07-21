"""Query service pour les exécutions de phase (table `pipeline_phase_executions`).

Adapter SA pour le port `PhaseExecutionsQueries`. L'écart de durée est recalculé à la lecture : le médian historique d'une phase se calcule sur ses exécutions réussies hors run courant, et le rapport de la durée courante à ce médian est exposé tel quel (aucun seuil ; l'œil juge une phase anormalement lente).
"""

from __future__ import annotations

from collections import defaultdict
from statistics import median as _statistics_median
from typing import cast

from sqlalchemy import Connection, text

from application.ports.api.pipeline_phase_executions_queries import (
    PhaseBrief,
    PhaseExecutionDetail,
    PhaseExecutionsQueries,
    RunDetail,
    RunSummary,
)
from application.ports.pipeline.phase_executions import (
    PhaseMetricsPayload,
    PhaseStatus,
    Signal,
)


def _median_duration(durations: list[float]) -> float | None:
    """Médian des durées historiques d'une phase, ou `None` si l'historique est vide."""
    return float(_statistics_median(durations)) if durations else None


def _duration_ratio(duration_s: float, historical_median_s: float | None) -> float | None:
    """Rapport de la durée courante au médian historique (> 1 = plus lent que d'habitude),
    `None` sans historique exploitable."""
    if historical_median_s is None or historical_median_s == 0:
        return None
    return duration_s / historical_median_s


class PgPhaseExecutionsQueries(PhaseExecutionsQueries):
    """Adapter SA pour `PhaseExecutionsQueries`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[RunSummary]:
        """Fenêtre de runs, plus récent en premier (`offset` runs sautés pour le
        chargement incrémental). Statut global = le pire des statuts de phase ; mode
        et sources pris sur la première phase du run."""
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
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
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
                       signals, metrics, details
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
            duration_s = float(metrics["duration_s"])
            median = _median_duration(history.get(r.phase, []))
            phases.append(
                PhaseExecutionDetail(
                    phase=r.phase,
                    started_at=r.started_at,
                    ended_at=r.ended_at,
                    status=cast(PhaseStatus, r.status),
                    duration_s=duration_s,
                    metrics=metrics,
                    details=r.details,
                    historical_median_duration_s=median,
                    duration_ratio=_duration_ratio(duration_s, median),
                    signals=cast("list[Signal]", r.signals),
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
