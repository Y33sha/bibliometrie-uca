"""Semis de paramètres de configuration, sur la connexion SQLAlchemy (`sa_sync_conn`)."""

import json

from sqlalchemy import Connection, text


def set_config(
    conn: Connection,
    key: str,
    value: object,
    description: str | None = None,
    *,
    replace: bool = True,
) -> bool:
    """Pose le paramètre `key` à `value`, sérialisé en jsonb, et renvoie vrai s'il est écrit. Sans `replace`, une valeur existante est gardée."""
    conflict = "DO UPDATE SET value = EXCLUDED.value" if replace else "DO NOTHING"
    written = conn.execute(
        text(
            "INSERT INTO config (key, value, description) "
            "VALUES (:key, CAST(:value AS jsonb), :description) "
            f"ON CONFLICT (key) {conflict} RETURNING key"
        ),
        {"key": key, "value": json.dumps(value), "description": description},
    ).scalar_one_or_none()
    return written is not None
