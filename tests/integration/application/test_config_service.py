"""Tests de caractérisation pour application/services/config/commands.py."""

import pytest

from application.services.config.commands import update_config_value
from domain.errors import NotFoundError
from infrastructure.repositories import config_repository
from tests.integration.helpers.config import insert_config


@pytest.fixture
def sync_config(sa_sync_conn):
    return config_repository(sa_sync_conn)


# ── update_config_value ────────────────────────────────────────────


class TestUpdateConfigValue:
    def test_raises_not_found(self, sa_sync_conn, sync_config):
        with pytest.raises(NotFoundError):
            update_config_value(sa_sync_conn, "nonexistent", "x", config=sync_config)

    def test_updates_existing(self, sa_sync_conn, sync_config):
        insert_config(sa_sync_conn, "test_key", "old")
        row = sync_config.update_config_value("test_key", "new")
        assert row is not None
        assert row["value"] == "new"

    def test_updates_with_dict_value(self, sa_sync_conn, sync_config):
        insert_config(sa_sync_conn, "test_key", {})
        row = sync_config.update_config_value("test_key", {"a": 1, "b": 2})
        assert row["value"] == {"a": 1, "b": 2}
