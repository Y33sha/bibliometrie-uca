"""Capture et persistance des exécutions de phase du pipeline.

`PhaseExecutionRecorder` est l'API offerte à l'orchestrateur : il génère le `run_id` au lancement et persiste une ligne dans `pipeline_phase_executions` par phase jouée. Tout est best-effort — une défaillance d'observabilité est loggée sans jamais interrompre le pipeline, et un recorder désactivé (connexion impossible, par exemple migration non appliquée) laisse le run tourner sans le tracer.

La colonne `details` rassemble les indicateurs sur-mesure que chaque phase remonte via son `PhaseMetrics` (conventions `summary`, `table`, `lines`, `matrix`). La connexion est utilisée en autocommit : chaque écriture est immédiate.
"""

from __future__ import annotations

import datetime
import json
import logging

from sqlalchemy import Connection, text

from application.ports.pipeline.phase_executions import (
    PhaseExecution,
    PhaseMetricsPayload,
    PhaseStatus,
    Signal,
)
from infrastructure.db.engine import get_sync_engine

log = logging.getLogger(__name__)


def next_run_id(conn: Connection) -> int:
    """Identifiant de run, issu de la séquence dédiée."""
    return int(conn.execute(text("SELECT nextval('pipeline_run_id_seq')")).scalar_one())


def persist_phase_execution(conn: Connection, execution: PhaseExecution) -> None:
    """Insère une ligne dans `pipeline_phase_executions`."""
    conn.execute(
        text(
            """
            INSERT INTO pipeline_phase_executions
                (run_id, phase, started_at, ended_at, mode, sources, status,
                 signals, metrics, details)
            VALUES
                (:run_id, :phase, :started_at, :ended_at, :mode, :sources, :status,
                 CAST(:signals AS jsonb), CAST(:metrics AS jsonb), CAST(:details AS jsonb))
            """
        ),
        {
            "run_id": execution.run_id,
            "phase": execution.phase,
            "started_at": execution.started_at,
            "ended_at": execution.ended_at,
            "mode": execution.mode,
            "sources": execution.sources,
            "status": execution.status,
            # `default=str` : une valeur non-JSON glissée dans `details` est stringifiée ; l'INSERT ne perd pas la ligne d'exécution de phase (best-effort).
            "signals": json.dumps(execution.signals, default=str),
            "metrics": json.dumps(execution.metrics, default=str),
            "details": json.dumps(execution.details, default=str),
        },
    )


def last_extract_date(conn: Connection, source: str) -> datetime.date | None:
    """Jour (UTC) de la dernière phase `extract` ayant inclus `source`, hors échec.

    Sert de borne « depuis » à l'extraction incrémentale : on repart de la dernière extraction réussie de cette source (un run partiel sans phase `extract` ne fait pas avancer le curseur). L'ancrage au jour de début (`started_at`) ménage un léger recouvrement, l'upsert staging étant idempotent. `status <> 'error'` écarte les extractions échouées.
    """
    last = conn.execute(
        text(
            """
            SELECT max(started_at)
            FROM pipeline_phase_executions
            WHERE phase = 'extract'
              AND :source = ANY(sources)
              AND status <> 'error'
            """
        ),
        {"source": source},
    ).scalar()
    return last.date() if last is not None else None


def get_last_extract_date(source: str) -> datetime.date | None:
    """Variante best-effort ouvrant sa propre connexion ; renvoie None (→ fallback de l'appelant) si la lecture échoue (table absente, connexion impossible)."""
    try:
        with get_sync_engine().connect() as conn:
            return last_extract_date(conn, source)
    except Exception as exc:
        log.warning("Lecture de la dernière extraction %s échouée : %s", source, exc)
        return None


class PhaseExecutionRecorder:
    """Capture par phase, best-effort. Désactivé quand `conn` est `None`."""

    def __init__(
        self,
        conn: Connection | None,
        run_id: int | None,
        *,
        mode: str,
        sources: list[str],
    ) -> None:
        self._conn = conn
        self._run_id = run_id
        self._mode = mode
        self._sources = sources

    @property
    def run_id(self) -> int | None:
        return self._run_id

    def record(
        self,
        *,
        phase: str,
        started_at: datetime.datetime,
        status: PhaseStatus,
        metrics: PhaseMetricsPayload,
        signals: list[Signal],
        details: dict[str, object],
    ) -> None:
        """Persiste l'exécution de la phase. `details` = indicateurs sur-mesure remontés par la phase via son `PhaseMetrics`."""
        if self._conn is None or self._run_id is None:
            return
        try:
            persist_phase_execution(
                self._conn,
                PhaseExecution(
                    run_id=self._run_id,
                    phase=phase,
                    started_at=started_at,
                    ended_at=datetime.datetime.now(datetime.UTC),
                    mode=self._mode,
                    sources=self._sources,
                    status=status,
                    metrics=metrics,
                    signals=signals,
                    details=details,
                ),
            )
        except Exception as exc:
            log.warning("Capture de la phase %s échouée : %s", phase, exc)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass


def start_run(*, mode: str, sources: list[str]) -> PhaseExecutionRecorder:
    """Ouvre la connexion d'observabilité et génère le `run_id`. Renvoie un recorder désactivé (sans tracer le run) si l'ouverture ou la séquence échoue."""
    try:
        conn = get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
        run_id = next_run_id(conn)
        return PhaseExecutionRecorder(conn, run_id, mode=mode, sources=sources)
    except Exception as exc:
        log.warning("Observabilité indisponible (run non tracé) : %s", exc)
        return PhaseExecutionRecorder(None, None, mode=mode, sources=sources)
