"""Capture et persistance des exécutions de phase du pipeline.

`PhaseExecutionRecorder` est l'API offerte à l'orchestrateur : il génère le
`run_id` au lancement, relève les volumes des tables touchées par chaque phase
(avant / après) et persiste une ligne dans `pipeline_phase_executions`. Tout est
best-effort — une défaillance d'observabilité est loggée sans jamais interrompre
le pipeline, et un recorder désactivé (connexion impossible, par exemple migration
non appliquée) laisse le run tourner sans le tracer.

La colonne `details` rassemble les indicateurs : `details["tables"]` porte le
volume avant / après des tables consommées et produites (relevé ici), et les
phases y ajoutent leurs indicateurs sur-mesure (conventions `summary`, `table`)
via leur `PhaseMetrics`. La connexion est utilisée en autocommit : chaque relevé
voit les données committées par les phases précédentes, chaque écriture est immédiate.
"""

from __future__ import annotations

import datetime
import json
import logging

from sqlalchemy import Connection, text

from application.ports.pipeline.phase_executions import (
    ObservableVolumes,
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


def snapshot_volumes(conn: Connection, tables: tuple[str, ...]) -> ObservableVolumes:
    """Volume (`COUNT(*)`) de chaque table. Les noms de tables proviennent du graphe
    des phases (constantes internes), jamais d'une entrée externe : l'interpolation
    de l'identifiant dans la requête est sûre (un identifiant ne se paramètre pas)."""
    volumes: ObservableVolumes = {}
    for table in tables:
        count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()  # noqa: S608
        volumes[table] = int(count) if count is not None else 0
    return volumes


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
            "signals": json.dumps(execution.signals),
            "metrics": json.dumps(execution.metrics),
            "details": json.dumps(execution.details),
        },
    )


def last_extract_date(conn: Connection, source: str) -> datetime.date | None:
    """Jour (UTC) de la dernière phase `extract` ayant inclus `source`, hors échec.

    Sert de borne « depuis » à l'extraction incrémentale : on repart de la dernière
    extraction réussie de cette source, pas d'un run quelconque — un run partiel sans
    phase `extract` ne fait donc pas avancer le curseur. L'ancrage au jour de début
    (`started_at`) ménage un léger recouvrement plutôt qu'un trou, l'upsert staging
    étant idempotent. `status <> 'error'` écarte les extractions échouées.
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
    """Variante best-effort ouvrant sa propre connexion ; renvoie None (→ fallback de
    l'appelant) si la lecture échoue (table absente, connexion impossible)."""
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

    def before_volumes(self, tables: tuple[str, ...]) -> ObservableVolumes | None:
        """Volume des `tables` touchées par la phase, relevé avant son exécution. Les tables
        proviennent du graphe des phases, fourni par l'orchestrateur (couche application)."""
        if self._conn is None:
            return None
        try:
            return snapshot_volumes(self._conn, tables)
        except Exception as exc:
            log.warning("Relevé d'avant-phase échoué : %s", exc)
            return None

    def record(
        self,
        *,
        phase: str,
        started_at: datetime.datetime,
        status: PhaseStatus,
        metrics: PhaseMetricsPayload,
        signals: list[Signal],
        details: dict[str, object],
        before_volumes: ObservableVolumes | None,
    ) -> None:
        """Relève les volumes après exécution et persiste l'exécution de la phase.

        `details` = indicateurs sur-mesure remontés par la phase ; on y ajoute
        `tables` (volumes avant/après) sans écraser ce que la phase a fourni.
        """
        if self._conn is None or self._run_id is None:
            return
        try:
            full_details: dict[str, object] = dict(details)
            if before_volumes is not None:
                try:
                    after = snapshot_volumes(self._conn, tuple(before_volumes))
                    full_details["tables"] = {
                        table: {
                            "before": before_volumes.get(table, 0),
                            "after": after.get(table, 0),
                        }
                        for table in before_volumes
                    }
                except Exception as exc:
                    log.warning("Relevé d'après-phase %s échoué : %s", phase, exc)
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
                    details=full_details,
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
    """Ouvre la connexion d'observabilité et génère le `run_id`. Renvoie un recorder
    désactivé (sans tracer le run) si l'ouverture ou la séquence échoue."""
    try:
        conn = get_sync_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
        run_id = next_run_id(conn)
        return PhaseExecutionRecorder(conn, run_id, mode=mode, sources=sources)
    except Exception as exc:
        log.warning("Observabilité indisponible (run non tracé) : %s", exc)
        return PhaseExecutionRecorder(None, None, mode=mode, sources=sources)
