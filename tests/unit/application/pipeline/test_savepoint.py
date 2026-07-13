"""Tests unitaires du context manager `application.pipeline._savepoint.savepoint`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.pipeline._savepoint import savepoint


def test_success_commits_savepoint():
    conn = MagicMock()
    sp = conn.begin_nested.return_value
    with savepoint(conn):
        pass
    sp.commit.assert_called_once()
    sp.rollback.assert_not_called()


def test_error_rolls_back_and_reraises():
    conn = MagicMock()
    sp = conn.begin_nested.return_value
    fallback = MagicMock()
    with pytest.raises(RuntimeError, match="boom"), savepoint(conn, on_rollback_failure=fallback):
        raise RuntimeError("boom")
    sp.rollback.assert_called_once()
    sp.commit.assert_not_called()
    fallback.assert_not_called()


def test_rollback_failure_triggers_fallback():
    """Si le rollback du SAVEPOINT échoue (transaction cassée), `on_rollback_failure` récupère la connexion et l'exception d'origine remonte."""
    conn = MagicMock()
    sp = conn.begin_nested.return_value
    sp.rollback.side_effect = RuntimeError("savepoint rollback fails")
    fallback = MagicMock()
    with pytest.raises(RuntimeError, match="boom"), savepoint(conn, on_rollback_failure=fallback):
        raise RuntimeError("boom")
    fallback.assert_called_once()
