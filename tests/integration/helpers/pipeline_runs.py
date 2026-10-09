"""Semis des exécutions de phases du pipeline, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

import datetime
import json

from sqlalchemy import Connection

from tests.integration.helpers.rows import insert_row


def insert_phase_execution(
    conn: Connection,
    run_id: int,
    *,
    phase: str,
    started_at: datetime.datetime,
    ended_at: datetime.datetime | None = None,
    mode: str,
    status: str,
    sources: list[str] | None = None,
    signals: list[object] | None = None,
    metrics: dict[str, object] | None = None,
    details: dict[str, object] | None = None,
) -> int:
    """Insère l'exécution de la phase `phase` du run `run_id` et renvoie son `id`. La fin vaut le début par défaut ; une colonne laissée à `None` prend la valeur par défaut du schéma."""
    return insert_row(
        conn,
        "pipeline_phase_executions",
        {
            "run_id": run_id,
            "phase": phase,
            "started_at": started_at,
            "ended_at": ended_at if ended_at is not None else started_at,
            "mode": mode,
            "sources": sources,
            "status": status,
            "signals": json.dumps(signals) if signals is not None else None,
            "metrics": json.dumps(metrics) if metrics is not None else None,
            "details": json.dumps(details) if details is not None else None,
        },
        {"sources": "text[]", "signals": "jsonb", "metrics": "jsonb", "details": "jsonb"},
    )
