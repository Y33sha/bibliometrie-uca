"""Tests unitaires de `merge_by_key.merge_publications_by_key`.

Le helper consolide les merges par batch de `pub_ids` partageant une clé (NNT, hal_id, ...) : résout les redirections accumulées dans le batch, choisit `min(pub_ids)` comme cible, fusionne les autres dedans via `merge_publications` + `refresh_from_sources`. Chaque fusion est encadrée par un SAVEPOINT individuel : un échec n'interrompt pas le batch.

Mocks : `merge_publications` et `refresh_from_sources` monkeypatchés pour capturer les appels et simuler des échecs ciblés. `Connection.begin_nested()` stubbé via `_FakeConn`.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from application.pipeline.publications import merge_by_key
from application.pipeline.publications.merge_by_key import merge_publications_by_key


class _FakeNested:
    """Stub minimal de `NestedTransaction`."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class _FakeConn:
    """Stub minimal de `Connection` : retourne un nested transaction.

    `begin_nested` est appelé une fois par tentative de merge (savepoint individuel).
    """

    def __init__(self) -> None:
        self.nested_calls: list[_FakeNested] = []

    def begin_nested(self) -> _FakeNested:
        nested = _FakeNested()
        self.nested_calls.append(nested)
        return nested


@pytest.fixture
def captured(monkeypatch):
    """Monkeypatche `merge_publications` et `refresh_from_sources` du module.

    Retourne un dict : `merge_calls`, `refresh_calls`, et `merge_raises` (mapping `source_id → Exception` pour simuler des échecs).
    """
    state: dict[str, Any] = {
        "merge_calls": [],
        "refresh_calls": [],
        "merge_raises": {},
    }

    def fake_merge(target_id, source_id, *, repo):  # noqa: ARG001
        state["merge_calls"].append((target_id, source_id))
        if source_id in state["merge_raises"]:
            raise state["merge_raises"][source_id]

    def fake_refresh(pub_id, *, repo):  # noqa: ARG001
        state["refresh_calls"].append(pub_id)

    monkeypatch.setattr(merge_by_key, "merge_publications", fake_merge)
    monkeypatch.setattr(merge_by_key, "refresh_from_sources", fake_refresh)
    return state


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_merge_by_key")


# ── Cas dégénérés ─────────────────────────────────────────────────


def test_empty_groups_returns_zero_zero(captured, logger):
    conn = _FakeConn()
    repo = MagicMock()

    merged, errors = merge_publications_by_key(conn, [], logger=logger, pub_repo=repo)

    assert (merged, errors) == (0, 0)
    assert captured["merge_calls"] == []


def test_single_resolved_id_is_skipped(captured, logger):
    """Si tous les `pub_ids` du groupe se réduisent à un seul après resolve : pas de merge."""
    conn = _FakeConn()
    repo = MagicMock()

    merged, errors = merge_publications_by_key(
        conn, [("key=X", [42])], logger=logger, pub_repo=repo
    )

    assert (merged, errors) == (0, 0)
    assert captured["merge_calls"] == []


# ── Happy path ────────────────────────────────────────────────────


def test_two_ids_merges_into_min(captured, logger):
    """Cas standard : 2 ids → target=min, source=max, un merge + un refresh."""
    conn = _FakeConn()
    repo = MagicMock()

    merged, errors = merge_publications_by_key(
        conn, [("key=X", [99, 10])], logger=logger, pub_repo=repo
    )

    assert (merged, errors) == (1, 0)
    assert captured["merge_calls"] == [(10, 99)]
    assert captured["refresh_calls"] == [10]
    # Savepoint committé.
    assert conn.nested_calls[0].committed is True
    assert conn.nested_calls[0].rolled_back is False


def test_multiple_sources_in_one_group_all_target_min(captured, logger):
    """3 ids → 2 merges, tous vers le min."""
    conn = _FakeConn()
    repo = MagicMock()

    merged, errors = merge_publications_by_key(
        conn, [("key=X", [50, 10, 30])], logger=logger, pub_repo=repo
    )

    assert (merged, errors) == (2, 0)
    assert captured["merge_calls"] == [(10, 30), (10, 50)]
    assert captured["refresh_calls"] == [10, 10]


def test_multiple_groups_independent(captured, logger):
    """Deux groupes indépendants : chacun mergé séparément."""
    conn = _FakeConn()
    repo = MagicMock()

    merged, errors = merge_publications_by_key(
        conn,
        [("key=X", [10, 11]), ("key=Y", [20, 21])],
        logger=logger,
        pub_repo=repo,
    )

    assert (merged, errors) == (2, 0)
    assert captured["merge_calls"] == [(10, 11), (20, 21)]


# ── Dry-run ───────────────────────────────────────────────────────


def test_dry_run_does_not_call_merge(captured, logger):
    conn = _FakeConn()
    repo = MagicMock()

    merged, errors = merge_publications_by_key(
        conn, [("key=X", [10, 99])], logger=logger, pub_repo=repo, dry_run=True
    )

    assert (merged, errors) == (1, 0)
    assert captured["merge_calls"] == []
    assert captured["refresh_calls"] == []
    # Aucun savepoint ouvert en dry-run.
    assert conn.nested_calls == []


# ── Échec d'un merge : batch continue ────────────────────────────


def test_merge_failure_increments_errors_and_continues(captured, logger):
    """Une exception sur un merge est attrapée → errors++, le batch continue."""
    conn = _FakeConn()
    repo = MagicMock()
    captured["merge_raises"] = {30: RuntimeError("DB constraint")}

    merged, errors = merge_publications_by_key(
        conn, [("key=X", [10, 20, 30, 40])], logger=logger, pub_repo=repo
    )

    # 4 ids → target=10, 3 tentatives de merge ; 1 échec (30) → 2 mergées, 1 erreur.
    assert (merged, errors) == (2, 1)
    # Toutes les tentatives ont eu lieu.
    assert captured["merge_calls"] == [(10, 20), (10, 30), (10, 40)]
    # Mais le refresh n'a été appelé QUE pour les succès.
    assert captured["refresh_calls"] == [10, 10]
    # Savepoint rollbacked pour l'échec.
    assert any(n.rolled_back for n in conn.nested_calls)


# ── Résolution des redirections cross-groupes ────────────────────


def test_redirect_resolution_uses_latest_target(captured, logger):
    """Si pub A a été mergée dans B au groupe 1, alors un groupe 2 contenant A doit rediriger vers B."""
    conn = _FakeConn()
    repo = MagicMock()

    # Groupe 1 : 10 + 99 → 99 mergée dans 10. Redirect 99 → 10.
    # Groupe 2 : 99 + 5 → après resolve : {10, 5} → target=5, source=10.
    merged, errors = merge_publications_by_key(
        conn,
        [("k1", [10, 99]), ("k2", [99, 5])],
        logger=logger,
        pub_repo=repo,
    )

    assert (merged, errors) == (2, 0)
    assert captured["merge_calls"] == [(10, 99), (5, 10)]


def test_redirect_chain_collapses_to_one(captured, logger):
    """Si après resolve un groupe se réduit à 1 seul id, il est skip (continue).

    Groupe 1 : 10 + 99 → redirect 99→10.
    Groupe 2 : 99 + 99 (formellement 2 ids mais après resolve : {10, 10} = {10}) → skip.
    """
    conn = _FakeConn()
    repo = MagicMock()

    merged, errors = merge_publications_by_key(
        conn,
        [("k1", [10, 99]), ("k2", [99, 99])],
        logger=logger,
        pub_repo=repo,
    )

    assert (merged, errors) == (1, 0)
    assert captured["merge_calls"] == [(10, 99)]


def test_redirect_chain_two_hops(captured, logger):
    """Redirect en chaîne : groupe 1 redirige 30→20, groupe 2 redirige 20→10, groupe 3 contenant 30 doit aller vers 10."""
    conn = _FakeConn()
    repo = MagicMock()

    # Groupe 1 : 20 + 30 → 30 redirige vers 20.
    # Groupe 2 : 10 + 20 → 20 redirige vers 10.
    # Groupe 3 : 30 + 99 → resolve(30) = resolve(20) = 10. Target=10, source=99.
    merged, errors = merge_publications_by_key(
        conn,
        [("k1", [20, 30]), ("k2", [10, 20]), ("k3", [30, 99])],
        logger=logger,
        pub_repo=repo,
    )

    assert (merged, errors) == (3, 0)
    assert captured["merge_calls"] == [(20, 30), (10, 20), (10, 99)]
