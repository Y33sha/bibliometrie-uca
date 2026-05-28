"""Tests unitaires de l'orchestrateur de déduplication par identifiant HAL.

Mocks : port `MergeQueries`, `Connection` (commit/rollback), `PublicationRepository`. `merge_publications_by_key` monkeypatché dans `run_merge` pour capturer les `groups` transmis. Pas de DB.

Couvre `find_merge_candidates` (pure shuffle) et `run_merge` (orchestration : merge + commit/rollback). La régression historique (OA+ScanR sur même hal_id) est dans `test_second_source_with_same_hal_id_is_not_dropped`.

Le path historique « SP HAL orpheline → lien simple » a été retiré (couvert désormais par `bulk_link_orphans_by_hal_id` côté `match_or_create_publications`).
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.publications import merge_pubs_by_hal_id
from application.pipeline.publications.merge_pubs_by_hal_id import (
    HalMergeItem,
    find_merge_candidates,
    run_merge,
)
from application.ports.pipeline.merge import HalSourceRow, OaScanrHalRow


class _FakeQueries:
    def __init__(
        self,
        src_rows: list[OaScanrHalRow],
        hal_rows: list[HalSourceRow],
    ) -> None:
        self._src_rows = src_rows
        self._hal_rows = hal_rows

    # `conn: object` car l'argument n'est pas utilisé dans le fake (les tests
    # passent `conn=None` ; le fake retourne directement les rows pré-fournies).
    def fetch_source_publications_with_hal_external_id(self, conn: object) -> list[OaScanrHalRow]:
        return self._src_rows

    def fetch_hal_source_publications(self, conn: object) -> list[HalSourceRow]:
        return self._hal_rows


def _src(source: str, src_pub_id: int | None, hal_id: str, src_doc_id: int = 1) -> OaScanrHalRow:
    return OaScanrHalRow(
        src_doc_id=src_doc_id,
        source=source,
        src_id=f"{source}-{src_doc_id}",
        src_pub_id=src_pub_id,
        hal_id=hal_id,
    )


def _hal(hal_id: str, hal_pub_id: int | None, hal_doc_id: int = 100) -> HalSourceRow:
    return HalSourceRow(hal_doc_id=hal_doc_id, halid=hal_id, hal_pub_id=hal_pub_id)


# ── Régression : OA + ScanR sur même hal_id ──────────────────────────


def test_second_source_with_same_hal_id_is_not_dropped():
    """Cas réel observé en prod (publi 160452 vs 86628 sur hal-05508565).

    OpenAlex est inséré en 1er et déjà fusionné à HAL (publi A=86628).
    ScanR arrive ensuite avec une publi distincte (publi B=160452).
    Le fix doit faire apparaître ScanR dans merge_needed.
    """
    src_rows = [
        _src("openalex", src_pub_id=86628, hal_id="hal-05508565", src_doc_id=1),
        _src("scanr", src_pub_id=160452, hal_id="hal-05508565", src_doc_id=2),
    ]
    hal_rows = [_hal("hal-05508565", hal_pub_id=86628, hal_doc_id=999)]

    merge_needed = find_merge_candidates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert len(merge_needed) == 1
    item = merge_needed[0]
    assert item.source == "scanr"
    assert item.src_pub_id == 160452
    assert item.hal_pub_id == 86628
    assert item.halid == "hal-05508565"


def test_no_op_when_both_sources_already_merged():
    """Si OA et ScanR sont toutes deux déjà fusionnées à la publi HAL → rien à faire."""
    src_rows = [
        _src("openalex", src_pub_id=42, hal_id="hal-X"),
        _src("scanr", src_pub_id=42, hal_id="hal-X", src_doc_id=2),
    ]
    hal_rows = [_hal("hal-X", hal_pub_id=42)]

    merge_needed = find_merge_candidates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert merge_needed == []


def test_hal_orphan_ignored():
    """SP HAL orpheline : ignorée par `find_merge_candidates`. Le rattachement est désormais entièrement délégué à `bulk_link_orphans_by_hal_id` (Phase B de match_or_create_publications)."""
    src_rows = [_src("openalex", src_pub_id=10, hal_id="hal-Y")]
    hal_rows = [_hal("hal-Y", hal_pub_id=None, hal_doc_id=500)]

    merge_needed = find_merge_candidates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert merge_needed == []


# ── merge_needed ──────────────────────────────────────────────────────


def test_merge_needed_dedup_same_pair_seen_twice():
    """Si deux sources non-HAL portent le même (src_pub, hal_pub) → un seul merge_needed."""
    src_rows = [
        _src("openalex", src_pub_id=20, hal_id="hal-W", src_doc_id=1),
        _src("scanr", src_pub_id=20, hal_id="hal-W", src_doc_id=2),
    ]
    hal_rows = [_hal("hal-W", hal_pub_id=21)]

    merge_needed = find_merge_candidates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert len(merge_needed) == 1


def test_no_match_when_hal_id_absent_from_hal_table():
    """Si le hal_id côté source non-HAL ne correspond à aucun source_publications HAL → ignoré."""
    src_rows = [_src("scanr", src_pub_id=30, hal_id="hal-orphan")]
    hal_rows = [_hal("hal-otherid", hal_pub_id=99)]

    merge_needed = find_merge_candidates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert merge_needed == []


# ── run_merge ─────────────────────────────────────────────────────────


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_merge_pubs_by_hal_id")


class _FakeConn:
    """Stub minimal de `sqlalchemy.Connection` — capture commit/rollback."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


@pytest.fixture
def patched(monkeypatch):
    """Monkeypatche `find_merge_candidates` et `merge_publications_by_key` du module.

    Retourne un dict `{find_result, find_calls, merge_result, merge_calls}` que les tests configurent avant l'appel.
    """
    state: dict[str, Any] = {
        "find_result": [],
        "find_calls": [],
        "merge_result": (0, 0),
        "merge_calls": [],
    }

    def fake_find(conn, queries):  # noqa: ARG001
        state["find_calls"].append(True)
        if isinstance(state["find_result"], Exception):
            raise state["find_result"]
        return state["find_result"]

    def fake_merge(conn, groups, *, logger, pub_repo, dry_run=False):  # noqa: ARG001
        groups_list = list(groups)
        state["merge_calls"].append({"groups": groups_list, "dry_run": dry_run})
        return state["merge_result"]

    monkeypatch.setattr(merge_pubs_by_hal_id, "find_merge_candidates", fake_find)
    monkeypatch.setattr(merge_pubs_by_hal_id, "merge_publications_by_key", fake_merge)
    return state


class TestRunMerge:
    def test_no_duplicates_short_circuits(self, patched, logger):
        conn = _FakeConn()
        repo = MagicMock()
        patched["find_result"] = []

        run_merge(conn, MagicMock(), logger, pub_repo=repo)

        assert patched["merge_calls"] == []
        assert conn.committed is False
        assert conn.rolled_back is False

    def test_merge_needed_triggers_merge_and_commit(self, patched, logger):
        conn = _FakeConn()
        repo = MagicMock()
        merge_item = HalMergeItem(
            source="openalex",
            src_id="openalex-1",
            src_pub_id=20,
            hal_pub_id=21,
            halid="hal-W",
        )
        patched["find_result"] = [merge_item]

        run_merge(conn, MagicMock(), logger, pub_repo=repo)

        assert len(patched["merge_calls"]) == 1
        call = patched["merge_calls"][0]
        assert call["groups"] == [("[openalex] openalex-1 ↔ hal-W", [20, 21])]
        assert call["dry_run"] is False
        assert conn.committed is True

    def test_dry_run_does_not_commit(self, patched, logger):
        conn = _FakeConn()
        repo = MagicMock()
        merge_item = HalMergeItem(
            source="openalex",
            src_id="openalex-1",
            src_pub_id=20,
            hal_pub_id=21,
            halid="hal-Z",
        )
        patched["find_result"] = [merge_item]

        run_merge(conn, MagicMock(), logger, pub_repo=repo, dry_run=True)

        assert patched["merge_calls"][0]["dry_run"] is True
        assert conn.committed is False
        assert conn.rolled_back is False

    def test_exception_triggers_rollback_and_reraises(self, patched, logger):
        conn = _FakeConn()
        repo = MagicMock()
        patched["find_result"] = RuntimeError("DB exploded")

        with pytest.raises(RuntimeError, match="DB exploded"):
            run_merge(conn, MagicMock(), logger, pub_repo=repo)

        assert conn.rolled_back is True
        assert conn.committed is False
