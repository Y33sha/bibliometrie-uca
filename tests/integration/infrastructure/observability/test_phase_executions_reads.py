"""Tests d'intégration : `last_extract_date`.

Régression : la date « depuis » du mode quotidien se cale sur la dernière phase
`extract` ayant inclus la source, et non sur le dernier run quelconque. Un run
partiel sans phase `extract` ne doit donc pas avancer le curseur (sinon une run
`publications` lancée le matin ferait chercher les dépôts HAL « depuis aujourd'hui »).

Les cas utilisent une source sentinelle : `last_extract_date` interroge la table
globalement (`max` toutes lignes confondues), et `pipeline_phase_executions` porte
des lignes committées par d'autres tests de la session. Une source propre au test
isole les assertions tout en exerçant la même logique (la spécificité « hal » n'est
que l'argument passé par l'orchestrateur).
"""

from __future__ import annotations

import datetime

from sqlalchemy import text

from infrastructure.observability.phase_executions import last_extract_date

SRC = "test_src_extract_date"
OTHER = "test_src_other"


def _insert_phase(conn, *, run_id, phase, started_at, sources, status="ok"):
    conn.execute(
        text(
            """
            INSERT INTO pipeline_phase_executions
                (run_id, phase, started_at, ended_at, mode, sources, status)
            VALUES
                (:run_id, :phase, :started_at, :started_at, 'daily', :sources, :status)
            """
        ),
        {
            "run_id": run_id,
            "phase": phase,
            "started_at": started_at,
            "sources": sources,
            "status": status,
        },
    )


def _at(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 6, day, 8, 0, tzinfo=datetime.UTC)


class TestLastExtractDate:
    def test_returns_day_of_latest_extract_with_source(self, sa_sync_conn):
        _insert_phase(sa_sync_conn, run_id=1, phase="extract", started_at=_at(10), sources=[SRC])
        _insert_phase(
            sa_sync_conn, run_id=2, phase="extract", started_at=_at(15), sources=[SRC, OTHER]
        )
        assert last_extract_date(sa_sync_conn, SRC) == datetime.date(2026, 6, 15)

    def test_partial_run_without_extract_does_not_advance(self, sa_sync_conn):
        _insert_phase(sa_sync_conn, run_id=1, phase="extract", started_at=_at(10), sources=[SRC])
        _insert_phase(
            sa_sync_conn, run_id=2, phase="publications", started_at=_at(20), sources=[SRC]
        )
        assert last_extract_date(sa_sync_conn, SRC) == datetime.date(2026, 6, 10)

    def test_extract_without_the_source_is_ignored(self, sa_sync_conn):
        _insert_phase(sa_sync_conn, run_id=1, phase="extract", started_at=_at(10), sources=[SRC])
        _insert_phase(sa_sync_conn, run_id=2, phase="extract", started_at=_at(20), sources=[OTHER])
        assert last_extract_date(sa_sync_conn, SRC) == datetime.date(2026, 6, 10)

    def test_failed_extract_is_ignored(self, sa_sync_conn):
        _insert_phase(sa_sync_conn, run_id=1, phase="extract", started_at=_at(10), sources=[SRC])
        _insert_phase(
            sa_sync_conn,
            run_id=2,
            phase="extract",
            started_at=_at(20),
            sources=[SRC],
            status="error",
        )
        assert last_extract_date(sa_sync_conn, SRC) == datetime.date(2026, 6, 10)

    def test_none_when_no_extract_for_source(self, sa_sync_conn):
        _insert_phase(
            sa_sync_conn, run_id=1, phase="publications", started_at=_at(10), sources=[SRC]
        )
        assert last_extract_date(sa_sync_conn, SRC) is None
