"""Tests de caractérisation pour services/config.py."""

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
from infrastructure.repositories import config_repository


@pytest.fixture
def repo(db):
    return config_repository(db)


# ── Helpers ────────────────────────────────────────────────────────


def _insert_config(db, key, value, description="desc"):
    db.execute(
        "INSERT INTO config (key, value, description) VALUES (%s, %s::jsonb, %s)",
        (key, json.dumps(value), description),
    )


def _insert_perimeter(db, code="test", name="Test", structure_ids=None):
    db.execute(
        "INSERT INTO perimeters (code, name, structure_ids) VALUES (%s, %s, %s) RETURNING id",
        (code, name, structure_ids or []),
    )
    return db.fetchone()["id"]


# ── update_config_value ────────────────────────────────────────────


class TestUpdateConfigValue:
    def test_raises_not_found(self, db, repo):
        with pytest.raises(NotFoundError):
            update_config_value(db, "nonexistent", "x", repo=repo)

    def test_updates_existing(self, db, repo):
        _insert_config(db, "test_key", "old")
        row = update_config_value(db, "test_key", "new", repo=repo)
        assert row is not None
        assert row["value"] == "new"

    def test_updates_with_dict_value(self, db, repo):
        _insert_config(db, "test_key", {})
        row = update_config_value(db, "test_key", {"a": 1, "b": 2}, repo=repo)
        assert row["value"] == {"a": 1, "b": 2}


# ── add_perimeter_structure ────────────────────────────────────────


class TestAddPerimeterStructure:
    def _create_struct(self, db, code="UCA"):
        db.execute(
            "INSERT INTO structures (code, name, structure_type) VALUES (%s, %s, 'universite'::structure_type) RETURNING id",
            (code, code),
        )
        return db.fetchone()["id"]

    def test_adds_new_structure(self, db, repo):
        s = self._create_struct(db)
        p = _insert_perimeter(db)
        assert add_perimeter_structure(db, p, s, repo=repo) == "added"
        db.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (p,))
        assert s in db.fetchone()["structure_ids"]

    def test_already_present(self, db, repo):
        s = self._create_struct(db)
        p = _insert_perimeter(db, structure_ids=[s])
        assert add_perimeter_structure(db, p, s, repo=repo) == "already_present"

    def test_perimeter_not_found(self, db, repo):
        with pytest.raises(NotFoundError):
            add_perimeter_structure(db, 999999, 1, repo=repo)


# ── remove_perimeter_structure ─────────────────────────────────────


class TestRemovePerimeterStructure:
    def test_removes_if_present(self, db, repo):
        p = _insert_perimeter(db, structure_ids=[1, 2, 3])
        remove_perimeter_structure(db, p, 2, repo=repo)
        db.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (p,))
        assert db.fetchone()["structure_ids"] == [1, 3]

    def test_idempotent_if_absent(self, db, repo):
        p = _insert_perimeter(db, structure_ids=[1])
        remove_perimeter_structure(db, p, 999, repo=repo)  # no-op : pas d'erreur

    def test_raises_if_perimeter_not_found(self, db, repo):
        with pytest.raises(NotFoundError):
            remove_perimeter_structure(db, 999999, 1, repo=repo)


# ── create_perimeter ───────────────────────────────────────────────


class TestCreatePerimeter:
    def test_creates(self, db, repo):
        pid = create_perimeter(
            db, code="new_perim", name="New Perimeter", description="desc", repo=repo
        )
        assert pid is not None
        db.execute("SELECT code, name FROM perimeters WHERE id = %s", (pid,))
        row = db.fetchone()
        assert row["code"] == "new_perim"
        assert row["name"] == "New Perimeter"

    def test_raises_on_code_conflict(self, db, repo):
        _insert_perimeter(db, code="existing")
        with pytest.raises(ConflictError):
            create_perimeter(db, code="existing", name="X", repo=repo)

    def test_raises_on_empty_code_or_name(self, db, repo):
        with pytest.raises(ValidationError):
            create_perimeter(db, code="", name="X", repo=repo)
        with pytest.raises(ValidationError):
            create_perimeter(db, code="X", name="", repo=repo)


# ── update_perimeter ───────────────────────────────────────────────


class TestUpdatePerimeter:
    def test_raises_not_found(self, db, repo):
        with pytest.raises(NotFoundError):
            update_perimeter(db, 999999, fields={"name": "X"}, repo=repo)

    def test_raises_on_empty_fields(self, db, repo):
        p = _insert_perimeter(db)
        with pytest.raises(ValidationError):
            update_perimeter(db, p, fields={}, repo=repo)

    def test_raises_if_no_valid_field(self, db, repo):
        """Seules name, description, structure_ids sont permises."""
        p = _insert_perimeter(db)
        with pytest.raises(ValidationError):
            update_perimeter(db, p, fields={"code": "other"}, repo=repo)  # code non modifiable

    def test_updates_name_and_description(self, db, repo):
        p = _insert_perimeter(db, name="Old")
        update_perimeter(db, p, fields={"name": "New", "description": "D"}, repo=repo)
        db.execute("SELECT name, description FROM perimeters WHERE id = %s", (p,))
        row = db.fetchone()
        assert row["name"] == "New"
        assert row["description"] == "D"

    def test_updates_structure_ids(self, db, repo):
        p = _insert_perimeter(db, structure_ids=[1])
        update_perimeter(db, p, fields={"structure_ids": [4, 5, 6]}, repo=repo)
        db.execute("SELECT structure_ids FROM perimeters WHERE id = %s", (p,))
        assert db.fetchone()["structure_ids"] == [4, 5, 6]


# ── delete_perimeter ───────────────────────────────────────────────


class TestDeletePerimeter:
    def test_raises_not_found(self, db, repo):
        with pytest.raises(NotFoundError):
            delete_perimeter(db, 999999, repo=repo)

    def test_deletes(self, db, repo):
        p = _insert_perimeter(db, code="disposable")
        delete_perimeter(db, p, repo=repo)
        db.execute("SELECT id FROM perimeters WHERE id = %s", (p,))
        assert db.fetchone() is None

    def test_raises_if_used_by_config(self, db, repo):
        """Si le périmètre est référencé dans config (perimeter_*), refus."""
        p = _insert_perimeter(db, code="used_perim")
        _insert_config(db, "perimeter_extraction", "used_perim")

        with pytest.raises(ConflictError, match="utilisé par"):
            delete_perimeter(db, p, repo=repo)

        # Le périmètre existe toujours
        db.execute("SELECT id FROM perimeters WHERE id = %s", (p,))
        assert db.fetchone() is not None
