"""Tests de caractérisation pour application/config.py (async)."""

import json

import pytest

from application.config import (
    add_perimeter_structure,
    create_perimeter,
    delete_perimeter,
    remove_perimeter_structure,
    update_config_value,
    update_perimeter,
)
from domain.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.repositories import async_config_repository


@pytest.fixture
def repo(async_db):
    return async_config_repository(async_db)


# ── Helpers ────────────────────────────────────────────────────────


async def _insert_config(db, key, value, description="desc"):
    await db.execute(
        "INSERT INTO config (key, value, description) VALUES (%s, %s::jsonb, %s)",
        (key, json.dumps(value), description),
    )


async def _insert_perimeter(db, code="test", name="Test", structure_ids=None):
    await db.execute(
        "INSERT INTO perimeters (code, name, structure_ids) VALUES (%s, %s, %s) RETURNING id",
        (code, name, structure_ids or []),
    )
    row = await db.fetchone()
    return row["id"]


async def _create_struct(db, code="UCA"):
    await db.execute(
        "INSERT INTO structures (code, name, structure_type) "
        "VALUES (%s, %s, 'universite'::structure_type) RETURNING id",
        (code, code),
    )
    row = await db.fetchone()
    return row["id"]


# ── update_config_value ────────────────────────────────────────────


class TestUpdateConfigValue:
    async def test_raises_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await update_config_value(async_db, "nonexistent", "x", repo=repo)

    async def test_updates_existing(self, async_db, repo):
        await _insert_config(async_db, "test_key", "old")
        row = await update_config_value(async_db, "test_key", "new", repo=repo)
        assert row is not None
        assert row["value"] == "new"

    async def test_updates_with_dict_value(self, async_db, repo):
        await _insert_config(async_db, "test_key", {})
        row = await update_config_value(async_db, "test_key", {"a": 1, "b": 2}, repo=repo)
        assert row["value"] == {"a": 1, "b": 2}


# ── add_perimeter_structure ────────────────────────────────────────


class TestAddPerimeterStructure:
    async def test_adds_new_structure(self, async_db, repo):
        s = await _create_struct(async_db)
        p = await _insert_perimeter(async_db)
        assert await add_perimeter_structure(async_db, p, s, repo=repo) == "added"
        await async_db.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (p,))
        row = await async_db.fetchone()
        assert s in row["structure_ids"]

    async def test_already_present(self, async_db, repo):
        s = await _create_struct(async_db)
        p = await _insert_perimeter(async_db, structure_ids=[s])
        assert await add_perimeter_structure(async_db, p, s, repo=repo) == "already_present"

    async def test_perimeter_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await add_perimeter_structure(async_db, 999999, 1, repo=repo)


# ── remove_perimeter_structure ─────────────────────────────────────


class TestRemovePerimeterStructure:
    async def test_removes_if_present(self, async_db, repo):
        p = await _insert_perimeter(async_db, structure_ids=[1, 2, 3])
        await remove_perimeter_structure(async_db, p, 2, repo=repo)
        await async_db.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (p,))
        row = await async_db.fetchone()
        assert row["structure_ids"] == [1, 3]

    async def test_idempotent_if_absent(self, async_db, repo):
        p = await _insert_perimeter(async_db, structure_ids=[1])
        await remove_perimeter_structure(async_db, p, 999, repo=repo)  # no-op : pas d'erreur

    async def test_raises_if_perimeter_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await remove_perimeter_structure(async_db, 999999, 1, repo=repo)


# ── create_perimeter ───────────────────────────────────────────────


class TestCreatePerimeter:
    async def test_creates(self, async_db, repo):
        pid = await create_perimeter(
            async_db, code="new_perim", name="New Perimeter", description="desc", repo=repo
        )
        assert pid is not None
        await async_db.execute("SELECT code, name FROM perimeters WHERE id = %s", (pid,))
        row = await async_db.fetchone()
        assert row["code"] == "new_perim"
        assert row["name"] == "New Perimeter"

    async def test_raises_on_code_conflict(self, async_db, repo):
        await _insert_perimeter(async_db, code="existing")
        with pytest.raises(ConflictError):
            await create_perimeter(async_db, code="existing", name="X", repo=repo)

    async def test_raises_on_empty_code_or_name(self, async_db, repo):
        with pytest.raises(ValidationError):
            await create_perimeter(async_db, code="", name="X", repo=repo)
        with pytest.raises(ValidationError):
            await create_perimeter(async_db, code="X", name="", repo=repo)


# ── update_perimeter ───────────────────────────────────────────────


class TestUpdatePerimeter:
    async def test_raises_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await update_perimeter(async_db, 999999, fields={"name": "X"}, repo=repo)

    async def test_raises_on_empty_fields(self, async_db, repo):
        p = await _insert_perimeter(async_db)
        with pytest.raises(ValidationError):
            await update_perimeter(async_db, p, fields={}, repo=repo)

    async def test_raises_if_no_valid_field(self, async_db, repo):
        """Seules name, description, structure_ids sont permises."""
        p = await _insert_perimeter(async_db)
        with pytest.raises(ValidationError):
            await update_perimeter(async_db, p, fields={"code": "other"}, repo=repo)

    async def test_updates_name_and_description(self, async_db, repo):
        p = await _insert_perimeter(async_db, name="Old")
        await update_perimeter(async_db, p, fields={"name": "New", "description": "D"}, repo=repo)
        await async_db.execute("SELECT name, description FROM perimeters WHERE id = %s", (p,))
        row = await async_db.fetchone()
        assert row["name"] == "New"
        assert row["description"] == "D"

    async def test_updates_structure_ids(self, async_db, repo):
        p = await _insert_perimeter(async_db, structure_ids=[1])
        await update_perimeter(async_db, p, fields={"structure_ids": [4, 5, 6]}, repo=repo)
        await async_db.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (p,))
        row = await async_db.fetchone()
        assert row["structure_ids"] == [4, 5, 6]


# ── delete_perimeter ───────────────────────────────────────────────


class TestDeletePerimeter:
    async def test_raises_not_found(self, async_db, repo):
        with pytest.raises(NotFoundError):
            await delete_perimeter(async_db, 999999, repo=repo)

    async def test_deletes(self, async_db, repo):
        p = await _insert_perimeter(async_db, code="disposable")
        await delete_perimeter(async_db, p, repo=repo)
        await async_db.execute("SELECT id FROM perimeters WHERE id = %s", (p,))
        assert await async_db.fetchone() is None

    async def test_raises_if_used_by_config(self, async_db, repo):
        """Si le périmètre est référencé dans config (perimeter_*), refus."""
        p = await _insert_perimeter(async_db, code="used_perim")
        await _insert_config(async_db, "perimeter_extraction", "used_perim")

        with pytest.raises(ConflictError, match="utilisé par"):
            await delete_perimeter(async_db, p, repo=repo)

        # Le périmètre existe toujours
        await async_db.execute("SELECT id FROM perimeters WHERE id = %s", (p,))
        assert await async_db.fetchone() is not None
