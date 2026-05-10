"""Tests d'intégration pour `infrastructure.db.queries.normalize_hal`."""

from sqlalchemy import text

from infrastructure.db.queries.normalize_hal import (
    fetch_hal_source_structures_for_cache,
)


class TestFetchHalSourceStructuresForCache:
    """La fonction est appelée par `preload_caches` du normalizer HAL avec
    une SA `Connection`. Renvoie une liste de tuples `(source_id, id, name)`."""

    def test_returns_tuples(self, sa_sync_conn):
        sa_sync_conn.execute(
            text("""
                INSERT INTO source_structures (source, source_id, name)
                VALUES ('hal', '12345', 'Lab Foo'), ('hal', '67890', 'Lab Bar'),
                       ('openalex', 'I999', 'Hors HAL')
            """)
        )
        rows = fetch_hal_source_structures_for_cache(sa_sync_conn)
        assert len(rows) == 2
        by_src = {src: (pid, name) for src, pid, name in rows}
        assert "12345" in by_src
        assert "67890" in by_src
        assert by_src["12345"][1] == "Lab Foo"
        assert by_src["67890"][1] == "Lab Bar"

    def test_handles_null_name_via_coalesce(self, sa_sync_conn):
        sa_sync_conn.execute(
            text("""
                INSERT INTO source_structures (source, source_id, name)
                VALUES ('hal', 'no-name-id', '')
            """)
        )
        rows = fetch_hal_source_structures_for_cache(sa_sync_conn)
        match = [r for r in rows if r[0] == "no-name-id"]
        assert len(match) == 1
        assert match[0][2] == ""
