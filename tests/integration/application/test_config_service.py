"""Tests de caractérisation pour application/services/config/commands.py."""

import json

import pytest
from sqlalchemy import text

from application.services.config.commands import update_config_value
from domain.errors import NotFoundError
from infrastructure.repositories import config_repository


@pytest.fixture
def sync_config(sa_sync_conn):
    return config_repository(sa_sync_conn)


# ── Helpers ────────────────────────────────────────────────────────


def _insert_config_sync(conn, key, value, description="desc"):
    conn.execute(
        text(
            "INSERT INTO config (key, value, description) "
            "VALUES (:key, CAST(:value AS jsonb), :description)"
        ),
        {"key": key, "value": json.dumps(value), "description": description},
    )


# ── update_config_value ────────────────────────────────────────────


class TestUpdateConfigValue:
    def test_raises_not_found(self, sa_sync_conn, sync_config):
        with pytest.raises(NotFoundError):
            update_config_value(sa_sync_conn, "nonexistent", "x", config=sync_config)

    def test_updates_existing(self, sa_sync_conn, sync_config):
        _insert_config_sync(sa_sync_conn, "test_key", "old")
        row = sync_config.update_config_value("test_key", "new")
        assert row is not None
        assert row["value"] == "new"

    def test_updates_with_dict_value(self, sa_sync_conn, sync_config):
        _insert_config_sync(sa_sync_conn, "test_key", {})
        row = sync_config.update_config_value("test_key", {"a": 1, "b": 2})
        assert row["value"] == {"a": 1, "b": 2}
