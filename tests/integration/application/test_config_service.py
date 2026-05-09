"""Tests de caractérisation pour application/config.py (async)."""

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
    async_config_store,
    async_perimeter_repository,
    config_store,
)


@pytest.fixture
def repo(sa_conn):
    return async_perimeter_repository(sa_conn)


@pytest.fixture
def config(sa_conn):
    return async_config_store(sa_conn)


@pytest.fixture
def sync_config(sa_sync_conn):
    return config_store(sa_sync_conn)


# ── Helpers ────────────────────────────────────────────────────────


async def _insert_config(conn, key, value, description="desc"):
    await conn.execute(
        text(
            "INSERT INTO config (key, value, description) "
            "VALUES (:key, CAST(:value AS jsonb), :description)"
        ),
        {"key": key, "value": json.dumps(value), "description": description},
    )


def _insert_config_sync(conn, key, value, description="desc"):
    conn.execute(
        text(
            "INSERT INTO config (key, value, description) "
            "VALUES (:key, CAST(:value AS jsonb), :description)"
        ),
        {"key": key, "value": json.dumps(value), "description": description},
    )


async def _insert_perimeter(conn, code="test", name="Test", structure_ids=None):
    result = await conn.execute(
        text(
            "INSERT INTO perimeters (code, name, structure_ids) "
            "VALUES (:code, :name, :structure_ids) RETURNING id"
        ),
        {"code": code, "name": name, "structure_ids": structure_ids or []},
    )
    return result.scalar_one()


async def _create_struct(conn, code="UCA"):
    result = await conn.execute(
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
    async def test_adds_new_structure(self, sa_conn, repo):
        s = await _create_struct(sa_conn)
        p = await _insert_perimeter(sa_conn)
        assert await add_perimeter_structure(sa_conn, p, s, repo=repo) == "added"
        result = await sa_conn.execute(
            text("SELECT structure_ids FROM perimeters WHERE id = :p"), {"p": p}
        )
        assert s in result.scalar_one()

    async def test_already_present(self, sa_conn, repo):
        s = await _create_struct(sa_conn)
        p = await _insert_perimeter(sa_conn, structure_ids=[s])
        assert await add_perimeter_structure(sa_conn, p, s, repo=repo) == "already_present"

    async def test_perimeter_not_found(self, sa_conn, repo):
        with pytest.raises(NotFoundError):
            await add_perimeter_structure(sa_conn, 999999, 1, repo=repo)


# ── remove_perimeter_structure ─────────────────────────────────────


class TestRemovePerimeterStructure:
    async def test_removes_if_present(self, sa_conn, repo):
        p = await _insert_perimeter(sa_conn, structure_ids=[1, 2, 3])
        await remove_perimeter_structure(sa_conn, p, 2, repo=repo)
        result = await sa_conn.execute(
            text("SELECT structure_ids FROM perimeters WHERE id = :p"), {"p": p}
        )
        assert result.scalar_one() == [1, 3]

    async def test_idempotent_if_absent(self, sa_conn, repo):
        p = await _insert_perimeter(sa_conn, structure_ids=[1])
        await remove_perimeter_structure(sa_conn, p, 999, repo=repo)  # no-op : pas d'erreur

    async def test_raises_if_perimeter_not_found(self, sa_conn, repo):
        with pytest.raises(NotFoundError):
            await remove_perimeter_structure(sa_conn, 999999, 1, repo=repo)


# ── create_perimeter ───────────────────────────────────────────────


class TestCreatePerimeter:
    async def test_creates(self, sa_conn, repo):
        pid = await create_perimeter(
            sa_conn, code="new_perim", name="New Perimeter", description="desc", repo=repo
        )
        assert pid is not None
        result = await sa_conn.execute(
            text("SELECT code, name FROM perimeters WHERE id = :pid"), {"pid": pid}
        )
        row = result.one()
        assert row.code == "new_perim"
        assert row.name == "New Perimeter"

    async def test_raises_on_code_conflict(self, sa_conn, repo):
        await _insert_perimeter(sa_conn, code="existing")
        with pytest.raises(ConflictError):
            await create_perimeter(sa_conn, code="existing", name="X", repo=repo)

    async def test_raises_on_empty_code_or_name(self, sa_conn, repo):
        with pytest.raises(ValidationError):
            await create_perimeter(sa_conn, code="", name="X", repo=repo)
        with pytest.raises(ValidationError):
            await create_perimeter(sa_conn, code="X", name="", repo=repo)


# ── update_perimeter ───────────────────────────────────────────────


class TestUpdatePerimeter:
    async def test_raises_not_found(self, sa_conn, repo):
        with pytest.raises(NotFoundError):
            await update_perimeter(sa_conn, 999999, fields={"name": "X"}, repo=repo)

    async def test_raises_on_empty_fields(self, sa_conn, repo):
        p = await _insert_perimeter(sa_conn)
        with pytest.raises(ValidationError):
            await update_perimeter(sa_conn, p, fields={}, repo=repo)

    async def test_raises_if_no_valid_field(self, sa_conn, repo):
        """Seules name, description, structure_ids sont permises."""
        p = await _insert_perimeter(sa_conn)
        with pytest.raises(ValidationError):
            await update_perimeter(sa_conn, p, fields={"code": "other"}, repo=repo)

    async def test_updates_name_and_description(self, sa_conn, repo):
        p = await _insert_perimeter(sa_conn, name="Old")
        await update_perimeter(sa_conn, p, fields={"name": "New", "description": "D"}, repo=repo)
        result = await sa_conn.execute(
            text("SELECT name, description FROM perimeters WHERE id = :p"), {"p": p}
        )
        row = result.one()
        assert row.name == "New"
        assert row.description == "D"

    async def test_updates_structure_ids(self, sa_conn, repo):
        p = await _insert_perimeter(sa_conn, structure_ids=[1])
        await update_perimeter(sa_conn, p, fields={"structure_ids": [4, 5, 6]}, repo=repo)
        result = await sa_conn.execute(
            text("SELECT structure_ids FROM perimeters WHERE id = :p"), {"p": p}
        )
        assert result.scalar_one() == [4, 5, 6]


# ── delete_perimeter ───────────────────────────────────────────────


class TestDeletePerimeter:
    async def test_raises_not_found(self, sa_conn, repo, config):
        with pytest.raises(NotFoundError):
            await delete_perimeter(sa_conn, 999999, repo=repo, config=config)

    async def test_deletes(self, sa_conn, repo, config):
        p = await _insert_perimeter(sa_conn, code="disposable")
        await delete_perimeter(sa_conn, p, repo=repo, config=config)
        result = await sa_conn.execute(text("SELECT id FROM perimeters WHERE id = :p"), {"p": p})
        assert result.first() is None

    async def test_raises_if_used_by_config(self, sa_conn, repo, config):
        """Si le périmètre est référencé dans config (perimeter_*), refus."""
        p = await _insert_perimeter(sa_conn, code="used_perim")
        await _insert_config(sa_conn, "perimeter_extraction", "used_perim")

        with pytest.raises(ConflictError, match="utilisé par"):
            await delete_perimeter(sa_conn, p, repo=repo, config=config)

        # Le périmètre existe toujours
        result = await sa_conn.execute(text("SELECT id FROM perimeters WHERE id = :p"), {"p": p})
        assert result.first() is not None
