"""Tests de caractérisation du service de configuration."""

import pytest

from domain.errors import NotFoundError
from infrastructure.repositories import config_repository
from interfaces.api.deps import config_service
from tests.integration.helpers.config import set_config


@pytest.fixture
def sync_config(sa_sync_conn):
    return config_repository(sa_sync_conn)


# ── update_config_value ────────────────────────────────────────────


class TestUpdateConfigValue:
    def test_raises_not_found(self, sa_sync_conn):
        with pytest.raises(NotFoundError):
            config_service(sa_sync_conn).update_config_value("nonexistent", "x")

    def test_updates_existing(self, sa_sync_conn, sync_config):
        set_config(sa_sync_conn, "test_key", "old")
        row = sync_config.update_config_value("test_key", "new")
        assert row is not None
        assert row["value"] == "new"

    def test_updates_with_dict_value(self, sa_sync_conn, sync_config):
        set_config(sa_sync_conn, "test_key", {})
        row = sync_config.update_config_value("test_key", {"a": 1, "b": 2})
        assert row["value"] == {"a": 1, "b": 2}
