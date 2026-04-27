"""Tests d'intégration pour `infrastructure.db.queries.normalize_hal`."""

from infrastructure.db.queries.normalize_hal import (
    fetch_hal_source_structures_for_cache,
)


class TestFetchHalSourceStructuresForCache:
    """La fonction est appelée par `preload_caches` du normalizer HAL avec
    un curseur dict_row. Doit fonctionner aussi avec un tuple cursor."""

    def test_returns_tuples_with_dict_cursor(self, db):
        # La fixture `db` est un curseur dict_row — c'est le mode utilisé
        # par le normalizer en production.
        db.execute(
            """
            INSERT INTO source_structures (source, source_id, name)
            VALUES ('hal', '12345', 'Lab Foo'), ('hal', '67890', 'Lab Bar'),
                   ('openalex', 'I999', 'Hors HAL')
            RETURNING id
            """
        )
        rows = fetch_hal_source_structures_for_cache(db)
        assert len(rows) == 2
        by_src = {src: (pid, name) for src, pid, name in rows}
        assert "12345" in by_src
        assert "67890" in by_src
        assert by_src["12345"][1] == "Lab Foo"
        assert by_src["67890"][1] == "Lab Bar"

    def test_handles_null_name_via_coalesce(self, db):
        db.execute(
            """
            INSERT INTO source_structures (source, source_id, name)
            VALUES ('hal', 'no-name-id', '')
            """
        )
        rows = fetch_hal_source_structures_for_cache(db)
        match = [r for r in rows if r[0] == "no-name-id"]
        assert len(match) == 1
        assert match[0][2] == ""
