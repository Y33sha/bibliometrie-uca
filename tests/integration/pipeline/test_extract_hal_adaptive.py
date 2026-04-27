"""Tests de l'extraction HAL adaptive (preview IDs → full-fetch ou incrémental).

Stratégie : monkeypatcher `fetch_collection_ids`, `_extract_full` et
`_extract_incremental` pour observer lequel est choisi. On ne teste pas
la plomberie HTTP/SQL (couverte par le helper retry) — on teste le
dispatch heuristique et les tags de collection.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from infrastructure.sources.hal import extract_hal


@pytest.fixture
def no_sleep(monkeypatch):
    """Désactive HAL_DELAY pour rendre les tests instantanés."""
    monkeypatch.setattr(extract_hal.time, "sleep", lambda *_: None)


@pytest.fixture
def spies(monkeypatch):
    """Remplace les deux chemins d'extraction par des spies simples."""
    calls = {"full": [], "incremental": []}

    def fake_full(url, query, collection_code, conn, existing_ids, total_count):
        calls["full"].append({"collection": collection_code, "total": total_count})
        return 0  # nb_new

    def fake_incremental(url, collection_code, orphans, known, conn, existing_ids):
        calls["incremental"].append(
            {
                "collection": collection_code,
                "orphans": list(orphans),
                "known": list(known),
            }
        )
        return len(orphans), len(known)  # (new, tagged)

    monkeypatch.setattr(extract_hal, "_extract_full", fake_full)
    monkeypatch.setattr(extract_hal, "_extract_incremental", fake_incremental)
    return calls


class TestAdaptiveDispatch:
    def test_incremental_mode_triggered_for_umbrella(self, monkeypatch, no_sleep, spies):
        """5000 papiers, 4995 connus, 5 orphelins.
        per_page=500 → full_fetch_pages=10. 5 < 10 → MODE INCRÉMENTAL.
        """
        preview_ids = [f"hal-{i}" for i in range(5000)]
        monkeypatch.setattr(extract_hal, "fetch_collection_ids", lambda *a, **kw: preview_ids)
        existing = {f"hal-{i}" for i in range(5, 5000)}

        total, new = extract_hal.extract_collection(
            collection_code="UMBRELLA",
            collection_label="Umbrella",
            conn=MagicMock(),
            existing_ids=existing,
            base_url="https://api.archives-ouvertes.fr/search/",
            years=[2025, 2026],
        )
        assert total == 5000
        assert spies["incremental"] and not spies["full"]
        call = spies["incremental"][0]
        assert call["collection"] == "UMBRELLA"
        assert sorted(call["orphans"]) == [f"hal-{i}" for i in range(5)]
        assert len(call["known"]) == 4995

    def test_full_fetch_mode_when_staging_empty(self, monkeypatch, no_sleep, spies):
        """100 papiers, staging vide → 100 orphelins, full_fetch_pages=1.
        100 ≥ 1 → MODE FULL-FETCH."""
        preview_ids = [f"hal-{i}" for i in range(100)]
        monkeypatch.setattr(extract_hal, "fetch_collection_ids", lambda *a, **kw: preview_ids)

        total, new = extract_hal.extract_collection(
            collection_code="FRESH",
            collection_label="Fresh",
            conn=MagicMock(),
            existing_ids=set(),
            base_url="https://api.archives-ouvertes.fr/search/",
            years=[2025, 2026],
        )
        assert total == 100
        assert spies["full"] and not spies["incremental"]
        assert spies["full"][0]["collection"] == "FRESH"
        assert spies["full"][0]["total"] == 100

    def test_boundary_orphans_equals_pages_picks_full(self, monkeypatch, no_sleep, spies):
        """Borne : orphans == full_fetch_pages → mode full-fetch (règle `<` stricte).
        1000 papiers, 998 connus, 2 orphelins. per_page=500 → pages=2. 2 < 2 = False.
        """
        preview_ids = [f"hal-{i}" for i in range(1000)]
        monkeypatch.setattr(extract_hal, "fetch_collection_ids", lambda *a, **kw: preview_ids)
        existing = {f"hal-{i}" for i in range(2, 1000)}

        total, new = extract_hal.extract_collection(
            collection_code="BOUNDARY",
            collection_label="Boundary",
            conn=MagicMock(),
            existing_ids=existing,
            base_url="https://api.archives-ouvertes.fr/search/",
            years=[2025],
        )
        assert total == 1000
        assert spies["full"] and not spies["incremental"]

    def test_boundary_orphans_less_than_pages_picks_incremental(self, monkeypatch, no_sleep, spies):
        """Borne inverse : orphans == pages - 1 → mode incrémental.
        1000 papiers, 999 connus, 1 orphelin. per_page=500 → pages=2. 1 < 2 = True."""
        preview_ids = [f"hal-{i}" for i in range(1000)]
        monkeypatch.setattr(extract_hal, "fetch_collection_ids", lambda *a, **kw: preview_ids)
        existing = {f"hal-{i}" for i in range(1, 1000)}

        total, _new = extract_hal.extract_collection(
            collection_code="JUSTBELOW",
            collection_label="JustBelow",
            conn=MagicMock(),
            existing_ids=existing,
            base_url="https://api.archives-ouvertes.fr/search/",
            years=[2025],
        )
        assert total == 1000
        assert spies["incremental"] and not spies["full"]

    def test_dry_run_skips_both_paths(self, monkeypatch, no_sleep, spies):
        preview_ids = [f"hal-{i}" for i in range(50)]
        monkeypatch.setattr(extract_hal, "fetch_collection_ids", lambda *a, **kw: preview_ids)

        total, new = extract_hal.extract_collection(
            collection_code="DRY",
            collection_label="Dry",
            conn=MagicMock(),
            existing_ids=set(),
            base_url="https://api.archives-ouvertes.fr/search/",
            years=[2025],
            dry_run=True,
        )
        assert total == 50
        assert new == 0
        assert not spies["full"] and not spies["incremental"]

    def test_empty_collection_returns_zero(self, monkeypatch, no_sleep, spies):
        monkeypatch.setattr(extract_hal, "fetch_collection_ids", lambda *a, **kw: [])

        total, new = extract_hal.extract_collection(
            collection_code="EMPTY",
            collection_label="Empty",
            conn=MagicMock(),
            existing_ids=set(),
            base_url="https://api.archives-ouvertes.fr/search/",
            years=[2025],
        )
        assert total == 0
        assert new == 0
        assert not spies["full"] and not spies["incremental"]


class TestExtractFullSafeguard:
    """Tests du safeguard qui évite les boucles infinies sur `_extract_full`."""

    def test_empty_docs_breaks_loop_even_if_start_below_total(self, monkeypatch, no_sleep):
        """Si l'API retourne une page vide alors que start < total_count
        (incohérence rare côté Solr), on sort du loop au lieu de spinner."""
        # fetch_page retourne toujours une page vide avec numFound=1000 → piège
        monkeypatch.setattr(
            extract_hal,
            "fetch_page",
            lambda *a, **kw: {"response": {"numFound": 1000, "docs": []}},
        )
        monkeypatch.setattr(extract_hal, "upsert_work", lambda *a, **kw: None)

        conn = MagicMock()
        # Ne doit pas tourner indéfiniment : retourne 0 docs traités
        total_new = extract_hal._extract_full(
            url="https://example/",
            query="q",
            collection_code="C",
            conn=conn,
            existing_ids=set(),
            total_count=1000,
        )
        assert total_new == 0  # sortie propre


class TestTagExistingWithCollection:
    def test_empty_hal_ids_skips_query(self):
        conn = MagicMock()
        n = extract_hal.tag_existing_with_collection(conn, [], "FOO")
        assert n == 0
        conn.cursor.assert_not_called()

    def test_executes_update_with_array_append(self):
        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 3
        conn.cursor.return_value.__enter__.return_value = cur

        n = extract_hal.tag_existing_with_collection(conn, ["hal-1", "hal-2", "hal-3"], "PRES_UCA")
        assert n == 3
        sql = cur.execute.call_args[0][0]
        assert "UPDATE staging" in sql
        assert "hal_collections" in sql
        assert "ANY(%s)" in sql
        params = cur.execute.call_args[0][1]
        assert params == (
            "PRES_UCA",
            "PRES_UCA",
            "PRES_UCA",
            ["hal-1", "hal-2", "hal-3"],
        )
        conn.commit.assert_called_once()


class _NoCommitConn:
    """Wrap une connexion réelle en neutralisant commit() pour que le
    rollback de la fixture `db` reste effectif."""

    def __init__(self, real_conn):
        self._conn = real_conn

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        pass


class TestTagExistingWithCollectionSql:
    """Exécute le vrai SQL contre la base de test pour attraper les bugs
    de typage côté Postgres (ex. cast manquant sur `array || element`)."""

    def test_append_collection_to_existing_array(self, db):
        db.execute(
            """
            INSERT INTO staging (source, source_id, raw_data, hal_collections)
            VALUES ('hal', 'hal-existing', '{}'::jsonb, ARRAY['OLD']::TEXT[])
            """
        )
        n = extract_hal.tag_existing_with_collection(
            _NoCommitConn(db.connection), ["hal-existing"], "GEOLAB"
        )
        assert n == 1
        db.execute(
            "SELECT hal_collections FROM staging WHERE source_id = 'hal-existing'"
        )
        assert db.fetchone()["hal_collections"] == ["OLD", "GEOLAB"]

    def test_init_collection_array_when_null(self, db):
        db.execute(
            """
            INSERT INTO staging (source, source_id, raw_data, hal_collections)
            VALUES ('hal', 'hal-null', '{}'::jsonb, NULL)
            """
        )
        n = extract_hal.tag_existing_with_collection(
            _NoCommitConn(db.connection), ["hal-null"], "GEOLAB"
        )
        assert n == 1
        db.execute(
            "SELECT hal_collections FROM staging WHERE source_id = 'hal-null'"
        )
        assert db.fetchone()["hal_collections"] == ["GEOLAB"]

    def test_no_duplicate_when_collection_already_present(self, db):
        db.execute(
            """
            INSERT INTO staging (source, source_id, raw_data, hal_collections)
            VALUES ('hal', 'hal-dup', '{}'::jsonb, ARRAY['GEOLAB']::TEXT[])
            """
        )
        n = extract_hal.tag_existing_with_collection(
            _NoCommitConn(db.connection), ["hal-dup"], "GEOLAB"
        )
        assert n == 1
        db.execute(
            "SELECT hal_collections FROM staging WHERE source_id = 'hal-dup'"
        )
        assert db.fetchone()["hal_collections"] == ["GEOLAB"]
