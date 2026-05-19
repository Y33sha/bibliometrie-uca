"""Tests unitaires de `application.pipeline.normalize.base.SourceNormalizer.run`.

Couvre la template method `run()` et ses chemins :
- mode `--reset` (commit + sortie immédiate)
- `total == 0` (rien à faire)
- happy path (success / skip / error mélangés, batch commit, post_process, summary)
- exception dans `process_work` sans SAVEPOINT (rollback + on_error)
- `KeyboardInterrupt` (commit pour préserver le travail)
- exception fatale en dehors de la boucle (rollback + relève)
- `_iter_rows` mode `FETCH_SUB_BATCH` (chargement par sous-lots)

Le test `_process_one` avec SAVEPOINT vit dans `tests/integration/pipeline/test_normalize_on_error_hook.py`.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize.base import SourceNormalizer
from application.ports.pipeline.staging import StagingRow


def _row(label: str) -> StagingRow:
    """Construit une StagingRow identifiable par son `source_id` pour les assertions."""
    return StagingRow(id=hash(label) & 0xFFFF, source_id=label, doi=None, raw_data={})


class _FakeStaging:
    """Stub minimal du port `StagingQueries`."""

    def __init__(self) -> None:
        self.reset_called = 0
        self.count_returns = 0
        self.pending_rows: list[StagingRow] = []
        self.batch_ids: list[int] = []
        self.batch_id_rows: dict[tuple[int, ...], list[StagingRow]] = {}

    def reset_processed_flag(self, conn, source: str) -> int:
        self.reset_called += 1
        return 42

    def count_pending_staging(self, conn, source: str) -> int:
        return self.count_returns

    def fetch_pending_staging(self, conn, source: str, *, limit: int) -> list[StagingRow]:
        return self.pending_rows[:limit]

    def fetch_pending_staging_ids(self, conn, source: str, *, limit: int) -> list[int]:
        # Le test dédié à `FETCH_SUB_BATCH` peuple `batch_ids` directement.
        # Pour les autres tests qui peuplent `pending_rows`, on dérive les ids.
        if self.batch_ids:
            return self.batch_ids[:limit]
        return [r.id for r in self.pending_rows[:limit]]

    def fetch_staging_by_ids(self, conn, ids: list[int], *, source: str) -> list[StagingRow]:
        if self.batch_id_rows:
            return self.batch_id_rows.get(tuple(ids), [])
        ids_set = set(ids)
        return [r for r in self.pending_rows if r.id in ids_set]


class _Norm(SourceNormalizer):
    """Normalizer instrumenté pour pinguer `run()`."""

    SOURCE = "test"
    DEFAULT_BATCH_SIZE = 2

    def __init__(
        self,
        staging: _FakeStaging,
        *,
        results: list[Any] | None = None,
        raises_on: set[str] | None = None,
    ) -> None:
        super().__init__(
            conn=MagicMock(), logger=logging.getLogger("test"), staging_queries=staging
        )
        self.results = results or []
        self.raises_on = raises_on or set()
        self.processed_rows: list[StagingRow] = []
        self.preload_called = False
        self.post_process_called = False
        self.cleanup_called = False
        self.on_error_called = 0

    def process_work(self, conn, row: StagingRow) -> bool | None:
        self.processed_rows.append(row)
        if row.source_id in self.raises_on:
            raise RuntimeError(f"boom on {row.source_id}")
        # Retourne le résultat indexé par position (True/None/False).
        idx = len(self.processed_rows) - 1
        if idx < len(self.results):
            return self.results[idx]
        return True

    def preload_caches(self, conn):
        self.preload_called = True

    def post_process(self, conn):
        self.post_process_called = True

    def cleanup(self):
        self.cleanup_called = True

    def on_error(self):
        self.on_error_called += 1


# ── --reset ───────────────────────────────────────────────────────


class TestRunReset:
    def test_reset_then_return(self, caplog):
        staging = _FakeStaging()
        norm = _Norm(staging)
        with caplog.at_level(logging.INFO):
            norm.run(argv=["--reset"])
        assert staging.reset_called == 1
        # Pas d'appel à _count_pending ni à preload_caches sur reset.
        assert norm.preload_called is False
        assert norm.conn.commit.called is True  # type: ignore[attr-defined]
        assert "Reset : 42" in caplog.text


# ── total == 0 ────────────────────────────────────────────────────


class TestRunNoWork:
    def test_nothing_to_do(self, caplog):
        staging = _FakeStaging()
        staging.count_returns = 0
        norm = _Norm(staging)
        with caplog.at_level(logging.INFO):
            norm.run(argv=[])
        # Pas de preload sur total=0 (sortie avant).
        assert norm.preload_called is False
        assert "Rien à faire" in caplog.text


# ── Happy path ────────────────────────────────────────────────────


class TestRunHappyPath:
    def test_processes_all_rows(self):
        staging = _FakeStaging()
        staging.count_returns = 3
        staging.pending_rows = [_row("r1"), _row("r2"), _row("r3")]
        norm = _Norm(staging, results=[True, True, True])
        norm.run(argv=[])
        assert norm.preload_called is True
        assert [r.source_id for r in norm.processed_rows] == ["r1", "r2", "r3"]
        assert norm.post_process_called is True
        assert norm.cleanup_called is True

    def test_mixes_success_skip_error(self, caplog):
        """`True` → processed, `None` → skipped, `False` → errors. Le log final reporte les 3 totaux."""
        staging = _FakeStaging()
        staging.count_returns = 3
        staging.pending_rows = [_row("ok"), _row("skip"), _row("err")]
        norm = _Norm(staging, results=[True, None, False])
        with caplog.at_level(logging.INFO):
            norm.run(argv=[])
        assert "Traités avec succès : 1" in caplog.text
        assert "Ignorés : 1" in caplog.text
        assert "Erreurs : 1" in caplog.text

    def test_batch_commit_logs_progress(self, caplog):
        """Avec DEFAULT_BATCH_SIZE=2, un commit + log au 2e traité."""
        staging = _FakeStaging()
        staging.count_returns = 4
        staging.pending_rows = [_row(s) for s in ("a", "b", "c", "d")]
        norm = _Norm(staging, results=[True, True, True, True])
        with caplog.at_level(logging.INFO):
            norm.run(argv=[])
        # Log progress contient "2/4" et "4/4" — mais seul "2/4 traités" passe par le batch commit.
        assert "2/4 traités" in caplog.text

    def test_progress_log_with_skip_and_error(self, caplog):
        """Le log de progression mentionne aussi les `ignorés` et `erreurs` quand >0."""
        staging = _FakeStaging()
        staging.count_returns = 2
        staging.pending_rows = [_row("a"), _row("b")]
        # 1 ok + 1 skip → done=2 (batch_size=2) → log avec skipped et 0 errors (errors=0 donc pas affiché).
        norm = _Norm(staging, results=[True, None])
        with caplog.at_level(logging.INFO):
            norm.run(argv=[])
        # "1 ignorés" doit apparaître dans le log progress
        assert "1 ignorés" in caplog.text

    def test_summary_stats_lines_logged(self, caplog):
        class _NormWithSummary(_Norm):
            def summary_stats(self, conn):
                return ["  table_a : 100", "  table_b : 250"]

        staging = _FakeStaging()
        staging.count_returns = 1
        staging.pending_rows = [_row("x")]
        norm = _NormWithSummary(staging, results=[True])
        with caplog.at_level(logging.INFO):
            norm.run(argv=[])
        assert "table_a : 100" in caplog.text
        assert "table_b : 250" in caplog.text

    def test_limit_caps_processing(self):
        """`--limit 1` limite à 1 row même si total=3."""
        staging = _FakeStaging()
        staging.count_returns = 3
        staging.pending_rows = [_row("a"), _row("b"), _row("c")]
        norm = _Norm(staging, results=[True, True, True])
        norm.run(argv=["--limit", "1"])
        assert [r.source_id for r in norm.processed_rows] == ["a"]


# ── Exception sans SAVEPOINT ──────────────────────────────────────


class TestRunExceptionWithoutSavepoint:
    def test_rollback_and_on_error_called(self, caplog):
        staging = _FakeStaging()
        staging.count_returns = 2
        staging.pending_rows = [_row("a"), _row("b")]
        norm = _Norm(staging, results=[True, True], raises_on={"a"})
        with caplog.at_level(logging.INFO):
            norm.run(argv=[])
        # USE_SAVEPOINT=False par défaut → conn.rollback + on_error appelés
        assert norm.on_error_called == 1
        # Le 2e row est quand même traité après le rollback du 1er.
        assert "b" in [r.source_id for r in norm.processed_rows]
        assert "Erreurs : 1" in caplog.text


# ── KeyboardInterrupt ─────────────────────────────────────────────


class TestRunKeyboardInterrupt:
    def test_commit_and_warning(self, caplog):
        staging = _FakeStaging()
        staging.count_returns = 1
        staging.pending_rows = [_row("a")]

        class _Kb(_Norm):
            def process_work(self, conn, row):
                raise KeyboardInterrupt

        norm = _Kb(staging, results=[True])
        with caplog.at_level(logging.WARNING):
            norm.run(argv=[])
        # KeyboardInterrupt n'est pas re-levé — un commit final est fait.
        assert "Interruption" in caplog.text


# ── Exception fatale ──────────────────────────────────────────────


class TestRunFatalException:
    def test_rollback_and_reraise(self, caplog):
        """Si `preload_caches` lève (avant la boucle), c'est une erreur fatale : rollback + log + reraise."""
        staging = _FakeStaging()
        staging.count_returns = 1
        staging.pending_rows = [_row("a")]

        class _Fatal(_Norm):
            def preload_caches(self, conn):
                raise RuntimeError("fatal preload")

        norm = _Fatal(staging)
        with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
            norm.run(argv=[])
        assert "Erreur fatale" in caplog.text
        assert norm.conn.rollback.called is True  # type: ignore[attr-defined]


# ── _iter_rows avec FETCH_SUB_BATCH ───────────────────────────────


class TestIterRowsSubBatch:
    def test_loads_by_subbatches(self):
        """`FETCH_SUB_BATCH=2` → chargement par sous-lots de 2 ids."""

        class _SubBatch(_Norm):
            FETCH_SUB_BATCH = 2

        staging = _FakeStaging()
        staging.batch_ids = [10, 20, 30]
        a, b, c = _row("a"), _row("b"), _row("c")
        staging.batch_id_rows = {(10, 20): [a, b], (30,): [c]}
        norm = _SubBatch(staging)
        rows = list(norm._iter_rows(MagicMock(), limit=3))
        assert rows == [a, b, c]
