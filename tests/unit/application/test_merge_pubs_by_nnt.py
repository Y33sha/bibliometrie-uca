"""Tests unitaires de l'orchestrateur `merge_pubs_by_nnt.run_merge`.

Mocks : port `MergeQueries`, `Connection` (commit/rollback uniquement), et `merge_publications_by_key` monkeypatché pour capturer les groupes passés. Pas de DB.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.publications import merge_pubs_by_nnt
from application.pipeline.publications.merge_pubs_by_nnt import run_merge
from application.ports.pipeline.merge import NntDuplicateRow


class _FakeQueries:
    def __init__(self, duplicates: list[NntDuplicateRow] | Exception) -> None:
        self._duplicates = duplicates

    def find_nnt_duplicates(self, conn: object) -> list[NntDuplicateRow]:
        if isinstance(self._duplicates, Exception):
            raise self._duplicates
        return self._duplicates


class _FakeConn:
    """Stub minimal de `sqlalchemy.Connection` : capture commit/rollback."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def captured_calls(monkeypatch):
    """Monkeypatche `merge_publications_by_key` pour capturer ses appels.

    Retourne une liste de dicts décrivant chaque appel (groupes + dry_run + ...). Le stub renvoie `(2, 0)` par défaut ; le test peut override via `stub_return`.
    """
    calls: list[dict[str, Any]] = []
    stub_return = (2, 0)

    def fake_merge_by_key(conn, groups, *, logger, pub_repo, dry_run=False):  # noqa: ARG001
        groups_list = list(groups)
        calls.append({"groups": groups_list, "dry_run": dry_run})
        return stub_return

    monkeypatch.setattr(merge_pubs_by_nnt, "merge_publications_by_key", fake_merge_by_key)
    return calls


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_merge_pubs_by_nnt")


def test_no_duplicates_short_circuits_without_commit(captured_calls, logger):
    """`find_nnt_duplicates` vide → log "Rien à faire", pas de merge, pas de commit."""
    conn = _FakeConn()
    queries = _FakeQueries(duplicates=[])
    repo = MagicMock()

    run_merge(conn, queries, logger, pub_repo=repo)

    assert captured_calls == []
    assert conn.committed is False
    assert conn.rolled_back is False


def test_happy_path_formats_groups_and_commits(captured_calls, logger):
    """Plusieurs NNT à fusionner : groups formatés `NNT=... (sources: ...)`, commit appelé."""
    conn = _FakeConn()
    duplicates = [
        NntDuplicateRow(nnt="2023UCFA0001", pub_ids=[10, 11], sources=["theses", "openalex"]),
        NntDuplicateRow(nnt="2023UCFA0042", pub_ids=[42, 43, 44], sources=["theses", "scanr"]),
    ]
    queries = _FakeQueries(duplicates=duplicates)
    repo = MagicMock()

    run_merge(conn, queries, logger, pub_repo=repo)

    assert len(captured_calls) == 1
    call = captured_calls[0]
    assert call["dry_run"] is False
    assert call["groups"] == [
        ("NNT=2023UCFA0001 (sources: theses, openalex)", [10, 11]),
        ("NNT=2023UCFA0042 (sources: theses, scanr)", [42, 43, 44]),
    ]
    assert conn.committed is True
    assert conn.rolled_back is False


def test_dry_run_does_not_commit(captured_calls, logger):
    """`dry_run=True` propagé à `merge_publications_by_key`, pas de commit."""
    conn = _FakeConn()
    duplicates = [NntDuplicateRow(nnt="2024UCFA0099", pub_ids=[99, 100], sources=["theses"])]
    queries = _FakeQueries(duplicates=duplicates)
    repo = MagicMock()

    run_merge(conn, queries, logger, pub_repo=repo, dry_run=True)

    assert captured_calls[0]["dry_run"] is True
    assert conn.committed is False
    assert conn.rolled_back is False


def test_exception_triggers_rollback_and_reraises(captured_calls, logger):
    """Toute exception (ici depuis `find_nnt_duplicates`) → rollback + re-raise."""
    conn = _FakeConn()
    boom = RuntimeError("DB exploded")
    queries = _FakeQueries(duplicates=boom)
    repo = MagicMock()

    with pytest.raises(RuntimeError, match="DB exploded"):
        run_merge(conn, queries, logger, pub_repo=repo)

    assert conn.rolled_back is True
    assert conn.committed is False
    assert captured_calls == []
