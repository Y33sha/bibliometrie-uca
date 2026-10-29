"""Tests de caractérisation du service des périmètres et de la lecture d'un périmètre par son repository."""

import pytest
from sqlalchemy import text

from application.ports.repositories.perimeter_repository import PerimeterUpdate
from domain.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.repositories import perimeter_repository
from interfaces.api.deps import perimeter_service
from tests.integration.helpers.config import set_config
from tests.integration.helpers.structures import insert_perimeter


@pytest.fixture
def repo(sa_sync_conn):
    return perimeter_repository(sa_sync_conn)


@pytest.fixture
def service(sa_sync_conn):
    return perimeter_service(sa_sync_conn)


# ── find_by_id ─────────────────────────────────────────────────────


class TestPerimeterFindById:
    def test_returns_none_if_missing(self, repo):
        assert repo.find_by_id(999999) is None

    def test_hydrates_minimal(self, sa_sync_conn, repo):
        pid = insert_perimeter(sa_sync_conn, "P1", name="Périmètre 1")
        p = repo.find_by_id(pid)
        assert p is not None
        assert p.id == pid
        assert p.code == "P1"
        assert p.name == "Périmètre 1"
        assert p.root_structure_ids == ()

    def test_hydrates_with_structure_ids(self, sa_sync_conn, repo):
        pid = insert_perimeter(sa_sync_conn, "P2", name="P2", root_structure_ids=[10, 20, 30])
        p = repo.find_by_id(pid)
        assert p is not None
        assert p.root_structure_ids == (10, 20, 30)


# ── create_perimeter ───────────────────────────────────────────────


class TestCreatePerimeter:
    def test_creates(self, sa_sync_conn, service):
        pid = service.create_perimeter(
            code="new_perim", name="New Perimeter", root_structure_ids=[]
        )
        assert pid is not None
        result = sa_sync_conn.execute(
            text("SELECT code, name FROM perimeters WHERE id = :pid"), {"pid": pid}
        )
        row = result.one()
        assert row.code == "new_perim"
        assert row.name == "New Perimeter"

    def test_raises_on_code_conflict(self, sa_sync_conn, service):
        insert_perimeter(sa_sync_conn, "existing", name="Test")
        with pytest.raises(ConflictError):
            service.create_perimeter(code="existing", name="X", root_structure_ids=[])

    def test_raises_on_empty_code_or_name(self, sa_sync_conn, service):
        with pytest.raises(ValidationError):
            service.create_perimeter(code="", name="X", root_structure_ids=[])
        with pytest.raises(ValidationError):
            service.create_perimeter(code="X", name="", root_structure_ids=[])


# ── update_perimeter ───────────────────────────────────────────────


class TestUpdatePerimeter:
    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.update_perimeter(999999, update=PerimeterUpdate(name="X"))

    def test_raises_on_empty_fields(self, sa_sync_conn, service):
        p = insert_perimeter(sa_sync_conn, "test", name="Test")
        with pytest.raises(ValidationError):
            service.update_perimeter(p, update=PerimeterUpdate())

    def test_updates_name(self, sa_sync_conn, service):
        p = insert_perimeter(sa_sync_conn, "test", name="Old")
        service.update_perimeter(p, update=PerimeterUpdate(name="New"))
        result = sa_sync_conn.execute(text("SELECT name FROM perimeters WHERE id = :p"), {"p": p})
        assert result.scalar_one() == "New"

    def test_updates_structure_ids(self, sa_sync_conn, service):
        p = insert_perimeter(sa_sync_conn, "test", root_structure_ids=[1], name="Test")
        service.update_perimeter(p, update=PerimeterUpdate(root_structure_ids=[4, 5, 6]))
        result = sa_sync_conn.execute(
            text("SELECT root_structure_ids FROM perimeters WHERE id = :p"), {"p": p}
        )
        assert result.scalar_one() == [4, 5, 6]


# ── delete_perimeter ───────────────────────────────────────────────


class TestDeletePerimeter:
    def test_raises_not_found(self, sa_sync_conn, service):
        with pytest.raises(NotFoundError):
            service.delete_perimeter(999999)

    def test_deletes(self, sa_sync_conn, service):
        p = insert_perimeter(sa_sync_conn, "disposable", name="Test")
        service.delete_perimeter(p)
        result = sa_sync_conn.execute(text("SELECT id FROM perimeters WHERE id = :p"), {"p": p})
        assert result.first() is None

    def test_raises_if_used_by_config(self, sa_sync_conn, service):
        """La suppression d'un périmètre désigné par une clé de configuration `perimeter_*` est refusée."""
        p = insert_perimeter(sa_sync_conn, "used_perim", name="Test")
        set_config(sa_sync_conn, "perimeter_extraction", "used_perim")

        with pytest.raises(ConflictError, match="utilisé par"):
            service.delete_perimeter(p)

        # Le périmètre reste en base.
        result = sa_sync_conn.execute(text("SELECT id FROM perimeters WHERE id = :p"), {"p": p})
        assert result.first() is not None
