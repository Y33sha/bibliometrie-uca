"""Tests d'intégration : `last_daily_extract_date`, borne « depuis » du mode quotidien.

`last_daily_extract_date` prend le maximum sur toute la table, et `pipeline_phase_executions` porte des lignes committées par d'autres tests de la session. Les cas se placent donc en 2099, après toute ligne réelle.
"""

from __future__ import annotations

import datetime

from sqlalchemy import text

from infrastructure.observability.phase_executions import last_daily_extract_date


def _insert_phase(conn, *, run_id, phase, started_at, mode="daily", status="ok"):
    conn.execute(
        text(
            """
            INSERT INTO pipeline_phase_executions
                (run_id, phase, started_at, ended_at, mode, sources, status)
            VALUES
                (:run_id, :phase, :started_at, :started_at, :mode, '{hal}', :status)
            """
        ),
        {
            "run_id": run_id,
            "phase": phase,
            "started_at": started_at,
            "mode": mode,
            "status": status,
        },
    )


def _at(day: int) -> datetime.datetime:
    return datetime.datetime(2099, 6, day, 8, 0, tzinfo=datetime.UTC)


class TestLastDailyExtractDate:
    def test_jour_de_la_derniere_extraction_quotidienne(self, sa_sync_conn):
        _insert_phase(sa_sync_conn, run_id=1, phase="extract", started_at=_at(10))
        _insert_phase(sa_sync_conn, run_id=2, phase="extract", started_at=_at(15))
        assert last_daily_extract_date(sa_sync_conn) == datetime.date(2099, 6, 15)

    def test_extraction_par_annees_ignoree(self, sa_sync_conn):
        """Cas réel : une extraction HAL bornée à 2020 ne ramène pas les dépôts récents."""
        _insert_phase(sa_sync_conn, run_id=1, phase="extract", started_at=_at(10))
        _insert_phase(sa_sync_conn, run_id=2, phase="extract", started_at=_at(20), mode="full")
        assert last_daily_extract_date(sa_sync_conn) == datetime.date(2099, 6, 10)

    def test_run_sans_extraction_ignore(self, sa_sync_conn):
        _insert_phase(sa_sync_conn, run_id=1, phase="extract", started_at=_at(10))
        _insert_phase(sa_sync_conn, run_id=2, phase="publications", started_at=_at(20))
        assert last_daily_extract_date(sa_sync_conn) == datetime.date(2099, 6, 10)

    def test_extraction_avec_signal_ignoree(self, sa_sync_conn):
        """HAL indisponible ou run interrompu : les notices non récupérées restent dans la fenêtre suivante."""
        _insert_phase(sa_sync_conn, run_id=1, phase="extract", started_at=_at(10))
        _insert_phase(sa_sync_conn, run_id=2, phase="extract", started_at=_at(20), status="warning")
        _insert_phase(sa_sync_conn, run_id=3, phase="extract", started_at=_at(25), status="error")
        assert last_daily_extract_date(sa_sync_conn) == datetime.date(2099, 6, 10)
