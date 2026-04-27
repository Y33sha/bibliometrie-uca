"""Tests du hook `on_error()` de `SourceNormalizer` (base).

Contexte : bug observé 2026-04-20 — FK violation sur
`source_authorship_addresses.address_id` parce que `PgAddressLinker._cache`
survivait à un rollback de transaction. Le hook `on_error()` invalide les
caches de références après chaque rollback (SAVEPOINT ou complet).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.normalize.base import SourceNormalizer


class _SpyNormalizer(SourceNormalizer):
    """Fake normalizer qui compte les appels à `on_error()`."""

    SOURCE = "spy"

    def __init__(
        self,
        conn: Any,
        logger: Any,
        staging_queries: Any,
        *,
        use_savepoint: bool = False,
        error_on_ids: set | None = None,
    ) -> None:
        super().__init__(conn, logger, staging_queries)
        # Override at instance level (ClassVar défini dans la classe)
        self.USE_SAVEPOINT = use_savepoint  # type: ignore[misc]
        self._error_on_ids = error_on_ids or set()
        self.on_error_calls = 0
        self.processed_ids: list[int] = []

    def process_work(self, cur: Any, row: Any) -> bool | None:
        self.processed_ids.append(row["id"])
        if row["id"] in self._error_on_ids:
            raise RuntimeError(f"boom on {row['id']}")
        return True

    def on_error(self) -> None:
        self.on_error_calls += 1


class TestOnErrorHook:
    # ── _process_one (chemin SAVEPOINT) ─────────────────────────

    def test_savepoint_success_no_on_error(self):
        normalizer = _SpyNormalizer(MagicMock(), MagicMock(), MagicMock(), use_savepoint=True)
        cur = MagicMock()
        normalizer._process_one(cur, {"id": 1})
        assert normalizer.on_error_calls == 0

    def test_savepoint_error_calls_on_error(self):
        normalizer = _SpyNormalizer(
            MagicMock(),
            MagicMock(),
            MagicMock(),
            use_savepoint=True,
            error_on_ids={42},
        )
        cur = MagicMock()
        with pytest.raises(RuntimeError):
            normalizer._process_one(cur, {"id": 42})
        assert normalizer.on_error_calls == 1

    def test_savepoint_error_rollback_also_fails_still_calls_on_error(self):
        """Si ROLLBACK TO SAVEPOINT échoue, on tombe sur conn.rollback() — et
        dans les deux cas, on_error doit être appelé (les caches restent
        invalidés pour la sécurité)."""
        conn = MagicMock()
        normalizer = _SpyNormalizer(
            conn, MagicMock(), MagicMock(), use_savepoint=True, error_on_ids={42}
        )
        cur = MagicMock()
        # Fait échouer le ROLLBACK TO SAVEPOINT → on tombe sur conn.rollback()
        cur.execute.side_effect = [
            None,  # SAVEPOINT OK
            RuntimeError("savepoint exec fails"),  # ROLLBACK TO échoue
        ]
        with pytest.raises(RuntimeError):
            normalizer._process_one(cur, {"id": 42})
        assert conn.rollback.called
        assert normalizer.on_error_calls == 1

    # ── run() (chemin non-SAVEPOINT) ────────────────────────────

    def test_non_savepoint_error_calls_on_error_and_rolls_back(self, monkeypatch):
        """Le chemin sans SAVEPOINT passe par `run()` : sur erreur, la conn
        est rollbackée *puis* on_error est appelée."""
        conn = MagicMock()
        conn.autocommit = False
        staging = MagicMock()
        staging.count_pending_staging.return_value = 3
        staging.fetch_pending_staging.return_value = iter([{"id": 1}, {"id": 42}, {"id": 3}])

        normalizer = _SpyNormalizer(
            conn,
            MagicMock(),
            staging,
            use_savepoint=False,
            error_on_ids={42},
        )
        # Force run() à utiliser nos args par défaut
        normalizer.run([])

        assert normalizer.processed_ids == [1, 42, 3]  # tous vus
        assert normalizer.on_error_calls == 1  # un seul échec
        assert conn.rollback.called

    def test_non_savepoint_no_error_no_on_error(self):
        conn = MagicMock()
        conn.autocommit = False
        staging = MagicMock()
        staging.count_pending_staging.return_value = 2
        staging.fetch_pending_staging.return_value = iter([{"id": 1}, {"id": 2}])

        normalizer = _SpyNormalizer(conn, MagicMock(), staging, use_savepoint=False)
        normalizer.run([])
        assert normalizer.on_error_calls == 0


class _IsolatedConn:
    """Wrap une connexion réelle en neutralisant commit() et close() pour
    que le rollback final de la fixture `db` reste effectif."""

    def __init__(self, real_conn):
        self._conn = real_conn

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        pass

    def rollback(self):
        self._conn.rollback()

    def close(self):
        pass

    @property
    def autocommit(self):
        return self._conn.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._conn.autocommit = value

    @property
    def info(self):
        return self._conn.info


class TestMakeCursorRespectsUseDictCursor:
    """`get_connection()` configure `row_factory=dict_row` au niveau
    connexion, donc `conn.cursor()` sans row_factory en hérite. Le
    normalizer doit forcer un tuple cursor explicite quand
    `USE_DICT_CURSOR=False` (cas HAL / WoS), sinon les unpacking par
    position dans `process_work` (`a, b, c = row`) reçoivent les noms de
    colonnes au lieu des valeurs."""

    def test_tuple_cursor_when_use_dict_cursor_false(self, db):
        normalizer = _SpyNormalizer(db.connection, MagicMock(), MagicMock())
        normalizer.USE_DICT_CURSOR = False  # type: ignore[misc]

        cur = normalizer._make_cursor()
        cur.execute("SELECT 1 AS a, 'x' AS b")
        row = cur.fetchone()
        assert isinstance(row, tuple)
        assert row == (1, "x")

    def test_dict_cursor_when_use_dict_cursor_true(self, db):
        normalizer = _SpyNormalizer(db.connection, MagicMock(), MagicMock())
        normalizer.USE_DICT_CURSOR = True  # type: ignore[misc]

        cur = normalizer._make_cursor()
        cur.execute("SELECT 1 AS a, 'x' AS b")
        row = cur.fetchone()
        assert not isinstance(row, tuple)
        assert row == {"a": 1, "b": "x"}


class TestRunHandlesInTransactionConnection:
    """run() doit accepter une connexion déjà en INTRANS (cas typique :
    le caller a fait un SELECT avant de passer la conn — ex: lecture
    `get_api_base_urls` dans run_pipeline._run_normalize_hal)."""

    def test_run_resets_intrans_connection(self, db):
        from psycopg.pq import TransactionStatus

        # Forcer la connexion en INTRANS via un SELECT (simule
        # `get_api_base_urls` exécuté avant l'appel au normalizer).
        db.execute("SELECT 1")
        assert (
            db.connection.info.transaction_status == TransactionStatus.INTRANS
        )

        staging = MagicMock()
        staging.count_pending_staging.return_value = 0  # early return
        normalizer = _SpyNormalizer(
            _IsolatedConn(db.connection),
            MagicMock(),
            staging,
            use_savepoint=False,
        )
        normalizer.run([])  # ne doit pas lever ProgrammingError
