"""Tests unitaires de l'orchestrateur `merge_pubs_by_pmid.run_merge`.

Mocks : port `MergeQueries`, `Connection` (commit/rollback), `merge_publications_by_key` monkeypatché. Pas de DB.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.publications import merge_pubs_by_pmid
from application.pipeline.publications.merge_pubs_by_pmid import run_merge
from application.ports.pipeline.merge import PmidDuplicateRow


class _FakeQueries:
    def __init__(self, duplicates: list[PmidDuplicateRow] | Exception) -> None:
        self._duplicates = duplicates

    def find_pmid_duplicates(self, conn: object) -> list[PmidDuplicateRow]:
        if isinstance(self._duplicates, Exception):
            raise self._duplicates
        return self._duplicates


class _FakeConn:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def captured_calls(monkeypatch):
    calls: list[dict[str, Any]] = []

    def fake_merge_by_key(conn, groups, *, logger, pub_repo, dry_run=False):  # noqa: ARG001
        calls.append({"groups": list(groups), "dry_run": dry_run})
        return (2, 0)

    monkeypatch.setattr(merge_pubs_by_pmid, "merge_publications_by_key", fake_merge_by_key)
    return calls


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_merge_pubs_by_pmid")


def test_no_duplicates_short_circuits_without_commit(captured_calls, logger):
    conn = _FakeConn()
    run_merge(conn, _FakeQueries(duplicates=[]), logger, pub_repo=MagicMock())
    assert captured_calls == []
    assert conn.committed is False


def test_happy_path_formats_groups_and_commits(captured_calls, logger):
    conn = _FakeConn()
    duplicates = [
        PmidDuplicateRow(pmid="28973220", pub_ids=[10, 11], sources=["openalex", "hal"]),
        PmidDuplicateRow(pmid="31000000", pub_ids=[42, 43], sources=["scanr"]),
    ]
    run_merge(conn, _FakeQueries(duplicates=duplicates), logger, pub_repo=MagicMock())
    assert len(captured_calls) == 1
    assert captured_calls[0]["dry_run"] is False
    assert captured_calls[0]["groups"] == [
        ("PMID=28973220 (sources: openalex, hal)", [10, 11]),
        ("PMID=31000000 (sources: scanr)", [42, 43]),
    ]
    assert conn.committed is True


def test_dry_run_does_not_commit(captured_calls, logger):
    conn = _FakeConn()
    duplicates = [PmidDuplicateRow(pmid="28973220", pub_ids=[99, 100], sources=["hal"])]
    run_merge(conn, _FakeQueries(duplicates=duplicates), logger, pub_repo=MagicMock(), dry_run=True)
    assert captured_calls[0]["dry_run"] is True
    assert conn.committed is False


def test_exception_triggers_rollback_and_reraises(captured_calls, logger):
    conn = _FakeConn()
    with pytest.raises(RuntimeError, match="boom"):
        run_merge(conn, _FakeQueries(duplicates=RuntimeError("boom")), logger, pub_repo=MagicMock())
    assert conn.rolled_back is True
    assert captured_calls == []
