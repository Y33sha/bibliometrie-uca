"""Tests de caractérisation pour application/services/perimeters/core.py et l'hydratation du PerimeterRepository."""

import json

import pytest
from sqlalchemy import text

from application.ports.repositories.perimeter_repository import PerimeterUpdate
from application.services.perimeters.core import (
    create_perimeter,
    delete_perimeter,
    update_perimeter,
)
from domain.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.queries.config import PgConfigQueries
from infrastructure.repositories import perimeter_repository


@pytest.fixture
def repo(sa_sync_conn):
    return perimeter_repository(sa_sync_conn)


@pytest.fixture
def sync_config(sa_sync_conn):
    return PgConfigQueries(sa_sync_conn)


# ── Helpers ────────────────────────────────────────────────────────


def _insert_config_sync(conn, key, value, description="desc"):
    conn.execute(
        text(
            "INSERT INTO config (key, value, description) "
            "VALUES (:key, CAST(:value AS jsonb), :description)"
        ),
        {"key": key, "value": json.dumps(value), "description": description},
    )


def _insert_perimeter_sync(conn, code="test", name="Test", structure_ids=None):
    result = conn.execute(
        text(
            "INSERT INTO perimeters (code, name, structure_ids) "
            "VALUES (:code, :name, :structure_ids) RETURNING id"
        ),
        {"code": code, "name": name, "structure_ids": structure_ids or []},
    )
    return result.scalar_one()


# ── find_by_id (hydratation Perimeter) ─────────────────────────────


class TestPerimeterFindById:
    def test_returns_none_if_missing(self, repo):
        assert repo.find_by_id(999999) is None

    def test_hydrates_minimal(self, sa_sync_conn, repo):
        pid = _insert_perimeter_sync(sa_sync_conn, code="P1", name="Périmètre 1")
        p = repo.find_by_id(pid)
        assert p is not None
        assert p.id == pid
        assert p.code == "P1"
        assert p.name == "Périmètre 1"
        assert p.structure_ids == ()

    def test_hydrates_with_structure_ids(self, sa_sync_conn, repo):
        pid = _insert_perimeter_sync(
            sa_sync_conn,
            code="P2",
            name="P2",
            structure_ids=[10, 20, 30],
        )
        p = repo.find_by_id(pid)
        assert p is not None
        assert p.structure_ids == (10, 20, 30)


# ── create_perimeter ───────────────────────────────────────────────


class TestCreatePerimeter:
    def test_creates(self, sa_sync_conn, repo):
        pid = create_perimeter(code="new_perim", name="New Perimeter", structure_ids=[], repo=repo)
        assert pid is not None
        result = sa_sync_conn.execute(
            text("SELECT code, name FROM perimeters WHERE id = :pid"), {"pid": pid}
        )
        row = result.one()
        assert row.code == "new_perim"
        assert row.name == "New Perimeter"

    def test_raises_on_code_conflict(self, sa_sync_conn, repo):
        _insert_perimeter_sync(sa_sync_conn, code="existing")
        with pytest.raises(ConflictError):
            create_perimeter(code="existing", name="X", structure_ids=[], repo=repo)

    def test_raises_on_empty_code_or_name(self, sa_sync_conn, repo):
        with pytest.raises(ValidationError):
            create_perimeter(code="", name="X", structure_ids=[], repo=repo)
        with pytest.raises(ValidationError):
            create_perimeter(code="X", name="", structure_ids=[], repo=repo)


# ── update_perimeter ───────────────────────────────────────────────


class TestUpdatePerimeter:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_perimeter(999999, update=PerimeterUpdate(name="X"), repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        p = _insert_perimeter_sync(sa_sync_conn)
        with pytest.raises(ValidationError):
            update_perimeter(p, update=PerimeterUpdate(), repo=repo)

    def test_updates_name(self, sa_sync_conn, repo):
        p = _insert_perimeter_sync(sa_sync_conn, name="Old")
        update_perimeter(p, update=PerimeterUpdate(name="New"), repo=repo)
        result = sa_sync_conn.execute(text("SELECT name FROM perimeters WHERE id = :p"), {"p": p})
        assert result.scalar_one() == "New"

    def test_updates_structure_ids(self, sa_sync_conn, repo):
        p = _insert_perimeter_sync(sa_sync_conn, structure_ids=[1])
        update_perimeter(p, update=PerimeterUpdate(structure_ids=[4, 5, 6]), repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT structure_ids FROM perimeters WHERE id = :p"), {"p": p}
        )
        assert result.scalar_one() == [4, 5, 6]


# ── delete_perimeter ───────────────────────────────────────────────


class TestDeletePerimeter:
    def test_raises_not_found(self, sa_sync_conn, repo, sync_config):
        with pytest.raises(NotFoundError):
            delete_perimeter(999999, repo=repo, config=sync_config)

    def test_deletes(self, sa_sync_conn, repo, sync_config):
        p = _insert_perimeter_sync(sa_sync_conn, code="disposable")
        delete_perimeter(p, repo=repo, config=sync_config)
        result = sa_sync_conn.execute(text("SELECT id FROM perimeters WHERE id = :p"), {"p": p})
        assert result.first() is None

    def test_raises_if_used_by_config(self, sa_sync_conn, repo, sync_config):
        """Si le périmètre est référencé dans config (perimeter_*), refus."""
        p = _insert_perimeter_sync(sa_sync_conn, code="used_perim")
        _insert_config_sync(sa_sync_conn, "perimeter_extraction", "used_perim")

        with pytest.raises(ConflictError, match="utilisé par"):
            delete_perimeter(p, repo=repo, config=sync_config)

        # Le périmètre existe toujours
        result = sa_sync_conn.execute(text("SELECT id FROM perimeters WHERE id = :p"), {"p": p})
        assert result.first() is not None
