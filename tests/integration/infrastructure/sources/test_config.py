"""Tests pour `infrastructure.sources.config.get_years`.

Vérifie les deux sémantiques de fenêtre d'années :
- `weekly` = offset glissant (`pipeline_years_weekly`),
- `full` = année d'ancre absolue (`pipeline_start_year_full`).
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
    def test_full_uses_absolute_start_year(self, sa_sync_conn):
        _set_config(sa_sync_conn, "pipeline_start_year_full", 2017)
        current = datetime.date.today().year
        assert get_years(sa_sync_conn, "full") == list(range(2017, current + 1))

    def test_weekly_uses_sliding_offset(self, sa_sync_conn):
        _set_config(sa_sync_conn, "pipeline_years_weekly", 1)
        current = datetime.date.today().year
        assert get_years(sa_sync_conn, "weekly") == [current - 1, current]

    def test_full_falls_back_to_current_year_when_unset(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'pipeline_start_year_full'"))
        current = datetime.date.today().year
        assert get_years(sa_sync_conn, "full") == [current]

    def test_full_falls_back_when_start_year_in_future(self, sa_sync_conn):
        current = datetime.date.today().year
        _set_config(sa_sync_conn, "pipeline_start_year_full", current + 5)
        assert get_years(sa_sync_conn, "full") == [current]
