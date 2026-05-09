"""Tests de caractérisation pour application/config.py."""

import json

import pytest
from sqlalchemy import text

from application.config import (
    add_perimeter_structure,
    create_perimeter,
    delete_perimeter,
    remove_perimeter_structure,
    update_config_value,
    update_perimeter,
)
from domain.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.repositories import (
    config_store,
    perimeter_repository,
)


@pytest.fixture
def repo(sa_sync_conn):
    return perimeter_repository(sa_sync_conn)


@pytest.fixture
def sync_config(sa_sync_conn):
    return config_store(sa_sync_conn)


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


def _create_struct_sync(conn, code="UCA"):
    result = conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES (:code, :name, 'universite'::structure_type) RETURNING id"
        ),
        {"code": code, "name": code},
    )
    return result.scalar_one()


# ── update_config_value ────────────────────────────────────────────


class TestUpdateConfigValue:
    def test_raises_not_found(self, sa_sync_conn, sync_config):
        with pytest.raises(NotFoundError):
            update_config_value(sa_sync_conn, "nonexistent", "x", config=sync_config)

    def test_updates_existing(self, sa_sync_conn, sync_config):
        _insert_config_sync(sa_sync_conn, "test_key", "old")
        row = update_config_value(sa_sync_conn, "test_key", "new", config=sync_config)
        assert row is not None
        assert row["value"] == "new"

    def test_updates_with_dict_value(self, sa_sync_conn, sync_config):
        _insert_config_sync(sa_sync_conn, "test_key", {})
        row = update_config_value(sa_sync_conn, "test_key", {"a": 1, "b": 2}, config=sync_config)
        assert row["value"] == {"a": 1, "b": 2}


# ── add_perimeter_structure ────────────────────────────────────────


class TestAddPerimeterStructure:
    def test_adds_new_structure(self, sa_sync_conn, repo):
        s = _create_struct_sync(sa_sync_conn)
        p = _insert_perimeter_sync(sa_sync_conn)
        assert add_perimeter_structure(sa_sync_conn, p, s, repo=repo) == "added"
        result = sa_sync_conn.execute(
            text("SELECT structure_ids FROM perimeters WHERE id = :p"), {"p": p}
        )
        assert s in result.scalar_one()

    def test_already_present(self, sa_sync_conn, repo):
        s = _create_struct_sync(sa_sync_conn)
        p = _insert_perimeter_sync(sa_sync_conn, structure_ids=[s])
        assert add_perimeter_structure(sa_sync_conn, p, s, repo=repo) == "already_present"

    def test_perimeter_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            add_perimeter_structure(sa_sync_conn, 999999, 1, repo=repo)


# ── remove_perimeter_structure ─────────────────────────────────────


class TestRemovePerimeterStructure:
    def test_removes_if_present(self, sa_sync_conn, repo):
        p = _insert_perimeter_sync(sa_sync_conn, structure_ids=[1, 2, 3])
        remove_perimeter_structure(sa_sync_conn, p, 2, repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT structure_ids FROM perimeters WHERE id = :p"), {"p": p}
        )
        assert result.scalar_one() == [1, 3]

    def test_idempotent_if_absent(self, sa_sync_conn, repo):
        p = _insert_perimeter_sync(sa_sync_conn, structure_ids=[1])
        remove_perimeter_structure(sa_sync_conn, p, 999, repo=repo)  # no-op : pas d'erreur

    def test_raises_if_perimeter_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            remove_perimeter_structure(sa_sync_conn, 999999, 1, repo=repo)


# ── create_perimeter ───────────────────────────────────────────────


class TestCreatePerimeter:
    def test_creates(self, sa_sync_conn, repo):
        pid = create_perimeter(
            sa_sync_conn, code="new_perim", name="New Perimeter", description="desc", repo=repo
        )
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
            create_perimeter(sa_sync_conn, code="existing", name="X", repo=repo)

    def test_raises_on_empty_code_or_name(self, sa_sync_conn, repo):
        with pytest.raises(ValidationError):
            create_perimeter(sa_sync_conn, code="", name="X", repo=repo)
        with pytest.raises(ValidationError):
            create_perimeter(sa_sync_conn, code="X", name="", repo=repo)


# ── update_perimeter ───────────────────────────────────────────────


class TestUpdatePerimeter:
    def test_raises_not_found(self, sa_sync_conn, repo):
        with pytest.raises(NotFoundError):
            update_perimeter(sa_sync_conn, 999999, fields={"name": "X"}, repo=repo)

    def test_raises_on_empty_fields(self, sa_sync_conn, repo):
        p = _insert_perimeter_sync(sa_sync_conn)
        with pytest.raises(ValidationError):
            update_perimeter(sa_sync_conn, p, fields={}, repo=repo)

    def test_raises_if_no_valid_field(self, sa_sync_conn, repo):
        """Seules name, description, structure_ids sont permises."""
        p = _insert_perimeter_sync(sa_sync_conn)
        with pytest.raises(ValidationError):
            update_perimeter(sa_sync_conn, p, fields={"code": "other"}, repo=repo)

    def test_updates_name_and_description(self, sa_sync_conn, repo):
        p = _insert_perimeter_sync(sa_sync_conn, name="Old")
        update_perimeter(sa_sync_conn, p, fields={"name": "New", "description": "D"}, repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT name, description FROM perimeters WHERE id = :p"), {"p": p}
        )
        row = result.one()
        assert row.name == "New"
        assert row.description == "D"

    def test_updates_structure_ids(self, sa_sync_conn, repo):
        p = _insert_perimeter_sync(sa_sync_conn, structure_ids=[1])
        update_perimeter(sa_sync_conn, p, fields={"structure_ids": [4, 5, 6]}, repo=repo)
        result = sa_sync_conn.execute(
            text("SELECT structure_ids FROM perimeters WHERE id = :p"), {"p": p}
        )
        assert result.scalar_one() == [4, 5, 6]


# ── delete_perimeter ───────────────────────────────────────────────


class TestDeletePerimeter:
    def test_raises_not_found(self, sa_sync_conn, repo, sync_config):
        with pytest.raises(NotFoundError):
            delete_perimeter(sa_sync_conn, 999999, repo=repo, config=sync_config)

    def test_deletes(self, sa_sync_conn, repo, sync_config):
        p = _insert_perimeter_sync(sa_sync_conn, code="disposable")
        delete_perimeter(sa_sync_conn, p, repo=repo, config=sync_config)
        result = sa_sync_conn.execute(text("SELECT id FROM perimeters WHERE id = :p"), {"p": p})
        assert result.first() is None

    def test_raises_if_used_by_config(self, sa_sync_conn, repo, sync_config):
        """Si le périmètre est référencé dans config (perimeter_*), refus."""
        p = _insert_perimeter_sync(sa_sync_conn, code="used_perim")
        _insert_config_sync(sa_sync_conn, "perimeter_extraction", "used_perim")

        with pytest.raises(ConflictError, match="utilisé par"):
            delete_perimeter(sa_sync_conn, p, repo=repo, config=sync_config)

        # Le périmètre existe toujours
        result = sa_sync_conn.execute(text("SELECT id FROM perimeters WHERE id = :p"), {"p": p})
        assert result.first() is not None
