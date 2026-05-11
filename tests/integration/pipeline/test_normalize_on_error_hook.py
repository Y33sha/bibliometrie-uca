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

    def process_work(self, conn: Any, row: Any) -> bool | None:
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
        """Si le rollback du SAVEPOINT échoue, on tombe sur conn.rollback() — et
        dans les deux cas, on_error doit être appelé (les caches restent
        invalidés pour la sécurité)."""
        conn = MagicMock()
        # `begin_nested()` retourne un sp dont .rollback() échoue
        sp = MagicMock()
        sp.rollback.side_effect = RuntimeError("savepoint rollback fails")
        conn.begin_nested.return_value = sp

        normalizer = _SpyNormalizer(
            conn, MagicMock(), MagicMock(), use_savepoint=True, error_on_ids={42}
        )
        with pytest.raises(RuntimeError):
            normalizer._process_one(conn, {"id": 42})
        assert conn.rollback.called
        assert normalizer.on_error_calls == 1

    # ── run() (chemin non-SAVEPOINT) ────────────────────────────

    def test_non_savepoint_error_calls_on_error_and_rolls_back(self):
        """Le chemin sans SAVEPOINT passe par `run()` : sur erreur, la conn
        est rollbackée *puis* on_error est appelée."""
        conn = MagicMock()
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
        staging = MagicMock()
        staging.count_pending_staging.return_value = 2
        staging.fetch_pending_staging.return_value = iter([{"id": 1}, {"id": 2}])

        normalizer = _SpyNormalizer(conn, MagicMock(), staging, use_savepoint=False)
        normalizer.run([])
        assert normalizer.on_error_calls == 0
