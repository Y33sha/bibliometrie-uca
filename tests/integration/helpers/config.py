"""Semis de paramètres de configuration, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

import json

from sqlalchemy import Connection, text


def set_config(conn: Connection, key: str, value: object, description: str | None = None) -> None:
    """Pose le paramètre `key` à `value`, sérialisé en jsonb, en remplaçant une valeur existante."""
    conn.execute(
        text(
            "INSERT INTO config (key, value, description) "
            "VALUES (:key, CAST(:value AS jsonb), :description) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"key": key, "value": json.dumps(value), "description": description},
    )
