"""Tests de l'extraction HAL adaptive (preview IDs → full-fetch ou incrémental).

Stratégie : un fake `HalExtractAdapter` (MagicMock) injecté à
`extract_collection`. On monkeypatche `_extract_full` et
`_extract_incremental` dans `application.pipeline.extract.extract_hal`
pour observer lequel est choisi. On ne teste pas la plomberie HTTP/SQL
(couverte par le helper retry + tests adapter dédiés).

Le rate-limit est interne à l'adapter (cf. `PgHalExtractAdapter._get`) :
l'orchestrateur n'appelle plus `time.sleep`, et les fakes MagicMock ne
dorment pas — aucun monkeypatch du sleep n'est nécessaire ici.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from application.pipeline.extract import extract_hal
from infrastructure.sources.hal.extract_hal import PgHalExtractAdapter


@pytest.fixture
def spies(monkeypatch):
    """Remplace les deux chemins d'extraction par des spies simples."""
    calls: dict[str, list] = {"full": [], "incremental": []}

    def fake_full(adapter, query, collection_code, conn, existing_ids, total_count, logger):
        calls["full"].append({"collection": collection_code, "total": total_count})
        return 0, 0, 0  # (new, updated, unchanged)

    def fake_incremental(adapter, collection_code, orphans, known, conn, existing_ids, logger):
        calls["incremental"].append(
            {
                "collection": collection_code,
                "orphans": list(orphans),
                "known": list(known),
            }
        )
        return (
            len(orphans),
            0,
            len(known),
        )  # (new, updated, unchanged) : connus = taggés (inchangés)

    monkeypatch.setattr(extract_hal, "_extract_full", fake_full)
    monkeypatch.setattr(extract_hal, "_extract_incremental", fake_incremental)
    return calls


def _fake_adapter(preview_ids: list[str]) -> MagicMock:
    """Construit un MagicMock du port HalExtractAdapter avec preview_ids fixé.

    `per_page_for` doit renvoyer un int réel (consommé par le calcul de
    pagination), et `build_query` une chaîne (passée telle quelle aux fetchs).
    """
    a = MagicMock()
    a.fetch_collection_ids.return_value = preview_ids
    a.per_page_for.return_value = 500
    a.build_query.return_value = "q"
    return a


class TestAdaptiveDispatch:
    def test_incremental_mode_triggered_for_umbrella(self, spies):
        """5000 papiers, 4995 connus, 5 orphelins.
        per_page=500 → full_fetch_pages=10. Seuil 10 × 10 = 100. 5 < 100 → INCRÉMENTAL.
        """
        preview_ids = [f"hal-{i}" for i in range(5000)]
        adapter = _fake_adapter(preview_ids)
        existing = {f"hal-{i}" for i in range(5, 5000)}

        total, _new, _updated, _unchanged = extract_hal.extract_collection(
            collection_code="UMBRELLA",
            collection_label="Umbrella",
            conn=MagicMock(),
            existing_ids=existing,
            adapter=adapter,
            logger=logging.getLogger("test"),
            years=[2025, 2026],
        )
        assert total == 5000
        assert spies["incremental"] and not spies["full"]
        call = spies["incremental"][0]
        assert call["collection"] == "UMBRELLA"
        assert sorted(call["orphans"]) == [f"hal-{i}" for i in range(5)]
        assert len(call["known"]) == 4995

    def test_full_fetch_mode_when_staging_empty(self, spies):
        """100 papiers, staging vide → 100 orphelins, full_fetch_pages=1.
        Seuil 10 × 1 = 10. 100 > 10 → FULL-FETCH."""
        preview_ids = [f"hal-{i}" for i in range(100)]
        adapter = _fake_adapter(preview_ids)

        total, _new, _updated, _unchanged = extract_hal.extract_collection(
            collection_code="FRESH",
            collection_label="Fresh",
            conn=MagicMock(),
            existing_ids=set(),
            adapter=adapter,
            logger=logging.getLogger("test"),
            years=[2025, 2026],
        )
        assert total == 100
        assert spies["full"] and not spies["incremental"]
        assert spies["full"][0]["collection"] == "FRESH"
        assert spies["full"][0]["total"] == 100

    def test_boundary_orphans_at_threshold_picks_full(self, spies):
        """Borne : orphans == 10 × full_fetch_pages → full (règle `<` stricte).
        5000 papiers, 4900 connus, 100 orphelins. per_page=500 → pages=10. Seuil 100. 100 < 100 = False.
        """
        preview_ids = [f"hal-{i}" for i in range(5000)]
        adapter = _fake_adapter(preview_ids)
        existing = {f"hal-{i}" for i in range(100, 5000)}

        total, _new, _updated, _unchanged = extract_hal.extract_collection(
            collection_code="BOUNDARY",
            collection_label="Boundary",
            conn=MagicMock(),
            existing_ids=existing,
            adapter=adapter,
            logger=logging.getLogger("test"),
            years=[2025],
        )
        assert total == 5000
        assert spies["full"] and not spies["incremental"]

    def test_boundary_orphans_just_below_threshold_picks_incremental(self, spies):
        """Borne inverse : orphans == seuil - 1 → incrémental.
        5000 papiers, 4901 connus, 99 orphelins. per_page=500 → pages=10. Seuil 100. 99 < 100 = True.
        """
        preview_ids = [f"hal-{i}" for i in range(5000)]
        adapter = _fake_adapter(preview_ids)
        existing = {f"hal-{i}" for i in range(99, 5000)}

        total, _new, _updated, _unchanged = extract_hal.extract_collection(
            collection_code="JUSTBELOW",
            collection_label="JustBelow",
            conn=MagicMock(),
            existing_ids=existing,
            adapter=adapter,
            logger=logging.getLogger("test"),
            years=[2025],
        )
        assert total == 5000
        assert spies["incremental"] and not spies["full"]

    def test_dry_run_skips_both_paths(self, spies):
        preview_ids = [f"hal-{i}" for i in range(50)]
        adapter = _fake_adapter(preview_ids)

        total, new, updated, unchanged = extract_hal.extract_collection(
            collection_code="DRY",
            collection_label="Dry",
            conn=MagicMock(),
            existing_ids=set(),
            adapter=adapter,
            logger=logging.getLogger("test"),
            years=[2025],
            dry_run=True,
        )
        assert total == 50
        assert (new, updated, unchanged) == (0, 0, 0)
        assert not spies["full"] and not spies["incremental"]

    def test_empty_collection_returns_zero(self, spies):
        adapter = _fake_adapter([])

        total, new, updated, unchanged = extract_hal.extract_collection(
            collection_code="EMPTY",
            collection_label="Empty",
            conn=MagicMock(),
            existing_ids=set(),
            adapter=adapter,
            logger=logging.getLogger("test"),
            years=[2025],
        )
        assert total == 0
        assert (new, updated, unchanged) == (0, 0, 0)
        assert not spies["full"] and not spies["incremental"]


class TestExtractFullSafeguard:
    """Tests du safeguard qui évite les boucles infinies sur `_extract_full`."""

    def test_empty_docs_breaks_loop_even_if_start_below_total(self):
        """Si l'API retourne une page vide alors que start < total_count
        (incohérence rare côté Solr), on sort du loop au lieu de spinner."""
        adapter = MagicMock()
        adapter.fetch_page.return_value = {"response": {"numFound": 1000, "docs": []}}

        conn = MagicMock()
        total_new, total_updated, total_unchanged = extract_hal._extract_full(
            adapter=adapter,
            query="q",
            collection_code="C",
            conn=conn,
            existing_ids=set(),
            total_count=1000,
            logger=logging.getLogger("test"),
        )
        assert (total_new, total_updated, total_unchanged) == (0, 0, 0)  # sortie propre
        adapter.upsert_work.assert_not_called()


# ── tag_existing_with_collection : tests SQL via l'adapter Pg ────


class _NoCommitConn:
    """Wrap une SA Connection en neutralisant commit() pour que le
    rollback de la fixture `sa_sync_conn` reste effectif."""

    def __init__(self, real_conn):
        self._conn = real_conn

    def execute(self, *args, **kwargs):
        return self._conn.execute(*args, **kwargs)

    def commit(self):
        pass


class TestTagExistingWithCollection:
    def test_empty_hal_ids_skips_query(self):
        adapter = PgHalExtractAdapter(base_url="https://example/")
        conn = MagicMock()
        n = adapter.tag_existing_with_collection(conn, [], "FOO")
        assert n == 0
        conn.execute.assert_not_called()

    def test_append_collection_to_existing_array(self, sa_sync_conn):
        adapter = PgHalExtractAdapter(base_url="https://example/")
        sa_sync_conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data, hal_collections) "
                "VALUES ('hal', 'hal-existing', '{}'::jsonb, ARRAY['OLD']::TEXT[])"
            )
        )
        n = adapter.tag_existing_with_collection(
            _NoCommitConn(sa_sync_conn), ["hal-existing"], "GEOLAB"
        )
        assert n == 1
        row = sa_sync_conn.execute(
            text("SELECT hal_collections FROM staging WHERE source_id = 'hal-existing'")
        ).one()
        assert row.hal_collections == ["OLD", "GEOLAB"]

    def test_init_collection_array_when_null(self, sa_sync_conn):
        adapter = PgHalExtractAdapter(base_url="https://example/")
        sa_sync_conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data, hal_collections) "
                "VALUES ('hal', 'hal-null', '{}'::jsonb, NULL)"
            )
        )
        n = adapter.tag_existing_with_collection(
            _NoCommitConn(sa_sync_conn), ["hal-null"], "GEOLAB"
        )
        assert n == 1
        row = sa_sync_conn.execute(
            text("SELECT hal_collections FROM staging WHERE source_id = 'hal-null'")
        ).one()
        assert row.hal_collections == ["GEOLAB"]

    def test_no_duplicate_when_collection_already_present(self, sa_sync_conn):
        adapter = PgHalExtractAdapter(base_url="https://example/")
        sa_sync_conn.execute(
            text(
                "INSERT INTO staging (source, source_id, raw_data, hal_collections) "
                "VALUES ('hal', 'hal-dup', '{}'::jsonb, ARRAY['GEOLAB']::TEXT[])"
            )
        )
        n = adapter.tag_existing_with_collection(_NoCommitConn(sa_sync_conn), ["hal-dup"], "GEOLAB")
        assert n == 1
        row = sa_sync_conn.execute(
            text("SELECT hal_collections FROM staging WHERE source_id = 'hal-dup'")
        ).one()
        assert row.hal_collections == ["GEOLAB"]
