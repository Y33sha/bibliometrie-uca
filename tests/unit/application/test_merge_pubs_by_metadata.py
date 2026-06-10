"""Tests unitaires de `merge_pubs_by_metadata.run_merge`.

Mocks : port `MetadataMergeQueries` (paires candidates + critères auteur/compteur en mémoire), `Connection` (commit/rollback), `merge_publications_by_key` monkeypatché. La compat auteur passe par la vraie fonction domaine `thesis_authors_compatible`.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.publications import merge_pubs_by_metadata
from application.pipeline.publications.merge_pubs_by_metadata import run_merge
from application.ports.pipeline.metadata_merge import MetadataMergeCandidatePair


class _FakeQueries:
    def __init__(self, pairs, *, authors=None, counts=None) -> None:
        self._pairs = pairs
        self._authors = authors or {}
        self._counts = counts or {}

    def find_metadata_merge_candidate_pairs(self, conn):  # noqa: ARG002
        return self._pairs

    def fetch_thesis_primary_author(self, conn, publication_id):  # noqa: ARG002
        return self._authors.get(publication_id)

    def fetch_max_source_authorship_count_per_publication(self, conn, publication_id):  # noqa: ARG002
        return self._counts.get(publication_id, 0)


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
        return (len(list(groups)), 0)

    monkeypatch.setattr(merge_pubs_by_metadata, "merge_publications_by_key", fake_merge_by_key)
    return calls


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_merge_pubs_by_metadata")


def _thesis_pair(a=1, b=2):
    return MetadataMergeCandidatePair(
        id_a=a, id_b=b, doc_type_a="thesis", doc_type_b="thesis", title_normalized="une these"
    )


def _proceedings_pair(a=1, b=2, title="x" * 40):
    return MetadataMergeCandidatePair(
        id_a=a, id_b=b, doc_type_a="proceedings", doc_type_b="proceedings", title_normalized=title
    )


# ── Thèse ─────────────────────────────────────────────────────────


def test_thesis_compatible_authors_merge(captured_calls, logger):
    queries = _FakeQueries(
        [_thesis_pair(10, 11)],
        authors={10: ("Dupont", "Jean"), 11: ("Dupont", "J")},
    )
    run_merge(_FakeConn(), queries, logger, pub_repo=MagicMock())
    assert [g[1] for g in captured_calls[0]["groups"]] == [[10, 11]]


def test_thesis_incompatible_authors_no_merge(captured_calls, logger):
    queries = _FakeQueries(
        [_thesis_pair(10, 11)],
        authors={10: ("Dupont", "Jean"), 11: ("Martin", "Paul")},
    )
    run_merge(_FakeConn(), queries, logger, pub_repo=MagicMock())
    assert captured_calls == []


def test_thesis_unknown_author_one_side_merges(captured_calls, logger):
    queries = _FakeQueries([_thesis_pair(10, 11)], authors={10: ("Dupont", "Jean"), 11: None})
    run_merge(_FakeConn(), queries, logger, pub_repo=MagicMock())
    assert [g[1] for g in captured_calls[0]["groups"]] == [[10, 11]]


# ── Proceedings ───────────────────────────────────────────────────


def test_proceedings_same_count_long_title_merges(captured_calls, logger):
    queries = _FakeQueries([_proceedings_pair(20, 21)], counts={20: 5, 21: 5})
    run_merge(_FakeConn(), queries, logger, pub_repo=MagicMock())
    assert [g[1] for g in captured_calls[0]["groups"]] == [[20, 21]]


def test_proceedings_short_title_no_merge(captured_calls, logger):
    queries = _FakeQueries([_proceedings_pair(20, 21, title="court")], counts={20: 5, 21: 5})
    run_merge(_FakeConn(), queries, logger, pub_repo=MagicMock())
    assert captured_calls == []


def test_proceedings_different_count_no_merge(captured_calls, logger):
    queries = _FakeQueries([_proceedings_pair(20, 21)], counts={20: 5, 21: 7})
    run_merge(_FakeConn(), queries, logger, pub_repo=MagicMock())
    assert captured_calls == []


# ── Dégénéré ──────────────────────────────────────────────────────


def test_no_candidates_no_commit(captured_calls, logger):
    conn = _FakeConn()
    run_merge(conn, _FakeQueries([]), logger, pub_repo=MagicMock())
    assert captured_calls == []
    assert conn.committed is False
