"""Tests pour `infrastructure.sources.config.get_years`.

`get_years` retourne `[start_year … année courante]` : `start_year` est
l'argument explicite (`--start-year`) ou, à défaut, la config absolue
`pipeline_start_year_full`.
"""

import datetime

from sqlalchemy import text

from infrastructure.sources.config import get_years


def _set_config(conn, key: str, value: int) -> None:
    conn.execute(text("DELETE FROM config WHERE key = :k"), {"k": key})
    conn.execute(
        text("INSERT INTO config (key, value) VALUES (:k, CAST(:v AS jsonb))"),
        {"k": key, "v": str(value)},
    )


class TestGetYears:
    def test_uses_config_anchor_when_no_argument(self, sa_sync_conn):
        _set_config(sa_sync_conn, "pipeline_start_year_full", 2017)
        current = datetime.date.today().year
        assert get_years(sa_sync_conn) == list(range(2017, current + 1))

    def test_explicit_start_year_overrides_config(self, sa_sync_conn):
        _set_config(sa_sync_conn, "pipeline_start_year_full", 2017)
        current = datetime.date.today().year
        assert get_years(sa_sync_conn, start_year=2020) == list(range(2020, current + 1))

    def test_falls_back_to_current_year_when_unset(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'pipeline_start_year_full'"))
        current = datetime.date.today().year
        assert get_years(sa_sync_conn) == [current]

    def test_falls_back_when_start_year_in_future(self, sa_sync_conn):
        current = datetime.date.today().year
        assert get_years(sa_sync_conn, start_year=current + 5) == [current]
