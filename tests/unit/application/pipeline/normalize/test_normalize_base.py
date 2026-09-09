"""Tests unitaires de `application.pipeline.normalize.base.SourceNormalizer.run`.

Couvre la template method `run()` et ses chemins :
- `total == 0` (rien à faire)
- happy path (success / skip / error mélangés, batch commit, summary)
- exception dans `process_work` (log de l'échec + rollback au SAVEPOINT)
- `KeyboardInterrupt` (rollback du batch en cours + re-raise pour arrêt propre)
- exception fatale en dehors de la boucle (rollback + relève)
- `_iter_rows` mode `FETCH_SUB_BATCH` (chargement par sous-lots)
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize.base import NormalizeStats, SourceNormalizer
from application.ports.pipeline.normalize.staging import StagingRow


def _row(label: str) -> StagingRow:
    """Construit une StagingRow identifiable par son `source_id` pour les assertions."""
    return StagingRow(id=hash(label) & 0xFFFF, source_id=label, doi=None, raw_data={})


class _FakeStaging:
    """Stub minimal du port `StagingQueries`."""

    def __init__(self) -> None:
        self.count_returns = 0
        self.pending_rows: list[StagingRow] = []
        self.batch_ids: list[int] = []
        self.batch_id_rows: dict[tuple[int, ...], list[StagingRow]] = {}

    def count_pending_staging(self, conn, source: str) -> int:
        return self.count_returns

    def fetch_pending_staging(self, conn, source: str, *, limit: int) -> list[StagingRow]:
        return self.pending_rows[:limit]

    def fetch_pending_staging_ids(self, conn, source: str) -> list[int]:
        # Le test dédié à `FETCH_SUB_BATCH` peuple `batch_ids` directement.
        # Pour les autres tests qui peuplent `pending_rows`, on dérive les ids.
        if self.batch_ids:
            return self.batch_ids
        return [r.id for r in self.pending_rows]

    def fetch_staging_by_ids(self, conn, ids: list[int]) -> list[StagingRow]:
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
        self.cleanup_called = False

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

    def cleanup(self):
        self.cleanup_called = True


# ── total == 0 ────────────────────────────────────────────────────


class TestRunNoWork:
    def test_nothing_to_do(self, caplog):
        """Une source sans document en attente se tait : la barre des autres reste lisible."""
        staging = _FakeStaging()
        staging.count_returns = 0
        norm = _Norm(staging)
        with caplog.at_level(logging.INFO):
            norm.run()
        # Pas de preload sur total=0 (sortie avant).
        assert norm.preload_called is False
        assert caplog.text == ""


# ── Happy path ────────────────────────────────────────────────────


class TestRunHappyPath:
    def test_processes_all_rows(self):
        staging = _FakeStaging()
        staging.count_returns = 3
        staging.pending_rows = [_row("r1"), _row("r2"), _row("r3")]
        norm = _Norm(staging, results=[True, True, True])
        norm.run()
        assert norm.preload_called is True
        assert [r.source_id for r in norm.processed_rows] == ["r1", "r2", "r3"]
        assert norm.cleanup_called is True

    def test_mixes_success_skip_error(self, caplog):
        """`True` → processed, `None` → skipped, `False` → errors. Seules les erreurs se lisent."""
        staging = _FakeStaging()
        staging.count_returns = 3
        staging.pending_rows = [_row("ok"), _row("skip"), _row("err")]
        norm = _Norm(staging, results=[True, None, False])
        with caplog.at_level(logging.INFO):
            stats = norm.run()
        assert "1 erreur" in caplog.text
        assert stats == NormalizeStats(processed=1, skipped=1, errors=1)

    def test_le_commit_tombe_a_chaque_lot(self):
        """Avec DEFAULT_BATCH_SIZE=2 sur quatre documents : deux commits de lot, plus celui de fin."""
        staging = _FakeStaging()
        staging.count_returns = 4
        staging.pending_rows = [_row(s) for s in ("a", "b", "c", "d")]
        norm = _Norm(staging, results=[True, True, True, True])
        norm.run()
        assert norm.conn.commit.call_count == 3

    def test_un_run_sans_erreur_se_tait(self, caplog):
        """La barre porte l'avancement ; le compte des ignorés remonte par les métriques."""
        staging = _FakeStaging()
        staging.count_returns = 2
        staging.pending_rows = [_row("a"), _row("b")]
        norm = _Norm(staging, results=[True, None])
        with caplog.at_level(logging.INFO):
            stats = norm.run()
        assert caplog.text == ""
        assert stats.skipped == 1


# ── Exception dans un work ────────────────────────────────────────


class TestRunWorkException:
    def test_savepoint_rollback_continues_batch(self, caplog):
        staging = _FakeStaging()
        staging.count_returns = 2
        staging.pending_rows = [_row("a"), _row("b")]
        norm = _Norm(staging, results=[True, True], raises_on={"a"})
        with caplog.at_level(logging.INFO):
            norm.run()
        # Le work en échec est loggé par la boucle (les process_work ne loggent pas eux-mêmes).
        assert "Erreur sur a" in caplog.text
        # Le 2e row est quand même traité après le rollback du 1er.
        assert "b" in [r.source_id for r in norm.processed_rows]
        assert "1 erreur" in caplog.text


# ── KeyboardInterrupt ─────────────────────────────────────────────


class TestRunKeyboardInterrupt:
    def test_rollback_and_reraise(self, caplog):
        staging = _FakeStaging()
        staging.count_returns = 1
        staging.pending_rows = [_row("a")]

        class _Kb(_Norm):
            def process_work(self, conn, row):
                raise KeyboardInterrupt

        norm = _Kb(staging, results=[True])
        with caplog.at_level(logging.WARNING), pytest.raises(KeyboardInterrupt):
            norm.run()
        # Le batch en cours est rollbacké (la transaction est avortée par le Ctrl+C ;
        # `commit()` lèverait `PendingRollbackError`), et le KeyboardInterrupt est
        # re-levé pour que `run_pipeline` arrête proprement (les batches committés
        # restent durables).
        assert "Interruption" in caplog.text
        norm.conn.rollback.assert_called()


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
            norm.run()
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
        rows = list(norm._iter_rows(MagicMock()))
        assert rows == [a, b, c]
