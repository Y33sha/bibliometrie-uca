"""Enregistrement des exécutions de phase du pipeline (`pipeline_phase_executions`).

`PhaseExecutionRecorder` génère le `run_id` au lancement, et écrit une ligne par phase jouée. Une défaillance de l'enregistrement est journalisée sans interrompre le pipeline ; un enregistreur désactivé (connexion impossible, migration non appliquée) laisse le run tourner sans trace.

La colonne `details` reçoit les indicateurs propres à chaque phase (`PhaseMetrics` : `summary`, `table`, `lines`, `matrix`). La connexion est en autocommit : chaque écriture est immédiate.
"""

from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from domain.pipeline_runs import PhaseMetricsPayload, PhaseStatus, Signal
from infrastructure.db.engine import get_sync_engine

log = logging.getLogger(__name__)


@dataclass
class PhaseExecution:
    """Une exécution de phase, prête à écrire."""

    run_id: int
    phase: str
    started_at: datetime.datetime
    ended_at: datetime.datetime
    mode: str
    sources: list[str]
    status: PhaseStatus
    metrics: PhaseMetricsPayload
    signals: list[Signal] = field(default_factory=list)
    # Indicateurs sur-mesure remontés par la phase (conventions `summary`, `table`, `lines`, `matrix` ; cf. `interfaces/frontend/.../phase-views.ts`).
    details: dict[str, object] = field(default_factory=dict)


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
            # `default=str` : une valeur non JSON de `details` devient une chaîne, et la ligne s'écrit.
            "signals": json.dumps(execution.signals, default=str),
            "metrics": json.dumps(execution.metrics, default=str),
            "details": json.dumps(execution.details, default=str),
        },
    )


def last_daily_extract_date(conn: Connection) -> datetime.date | None:
    """Jour (UTC) de début de la dernière phase `harvest` du mode `daily` terminée sans signal.

    Ce jour borne le moissonnage incrémental suivant. Un moissonnage par années laisse la borne en place. Le mode `daily` moissonne HAL seul : le statut `ok` garantit que HAL a abouti. Partir du jour de début ménage un léger recouvrement, sans dommage : l'écriture dans `staging` est idempotente.
    """
    last = conn.execute(
        text(
            """
            SELECT max(started_at)
            FROM pipeline_phase_executions
            WHERE phase = 'harvest' AND mode = 'daily' AND status = 'ok'
            """
        )
    ).scalar()
    return last.date() if last is not None else None


def get_last_daily_harvest_date() -> datetime.date | None:
    """Même lecture sur sa propre connexion ; `None` si elle échoue (table absente, connexion impossible), et l'appelant prend sa valeur par défaut."""
    try:
        with get_sync_engine().connect() as conn:
            return last_daily_extract_date(conn)
    except Exception as exc:
        log.warning("Lecture de la dernière extraction quotidienne échouée : %s", exc)
        return None


class PhaseExecutionRecorder:
    """Enregistreur des exécutions de phase, désactivé sans connexion."""

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
        """Écrit l'exécution de la phase, avec les indicateurs que la phase remonte (`details`)."""
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
            except Exception as exc:
                log.debug("Fermeture de la connexion d'observabilité échouée : %s", exc)


def start_run(*, mode: str, sources: list[str]) -> PhaseExecutionRecorder:
    """Ouvre la connexion d'observabilité et génère le `run_id`. Renvoie un enregistreur désactivé si l'ouverture ou la séquence échoue."""
    try:
        conn = get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
        run_id = next_run_id(conn)
        return PhaseExecutionRecorder(conn, run_id, mode=mode, sources=sources)
    except Exception as exc:
        log.warning("Observabilité indisponible (run non tracé) : %s", exc)
        return PhaseExecutionRecorder(None, None, mode=mode, sources=sources)
