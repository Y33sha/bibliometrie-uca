"""Tests unitaires du context manager `application.pipeline._savepoint.savepoint`."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from application.pipeline._savepoint import rollback_unless_invalidated, savepoint


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


def test_fallback_failure_keeps_original_exception():
    """Sur une connexion perdue, le rollback de secours échoue lui aussi : l'exception d'origine remonte quand même."""
    conn = MagicMock()
    conn.begin_nested.return_value.rollback.side_effect = RuntimeError("savepoint rollback fails")
    fallback = MagicMock(side_effect=RuntimeError("Can't reconnect until invalid transaction"))
    with (
        pytest.raises(ValueError, match="cause d'origine"),
        savepoint(conn, on_rollback_failure=fallback),
    ):
        raise ValueError("cause d'origine")


def test_rollback_unless_invalidated():
    conn = MagicMock(invalidated=False)
    rollback_unless_invalidated(conn)
    conn.rollback.assert_called_once()

    lost = MagicMock(invalidated=True)
    rollback_unless_invalidated(lost)
    lost.rollback.assert_not_called()
