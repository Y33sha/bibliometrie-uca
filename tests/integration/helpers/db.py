"""Connexion à la base de test sous le propriétaire du schéma.

Les tests d'intégration de l'API sèment leur jeu de données dans toutes les tables. Ce gestionnaire de contexte leur ouvre un curseur sous le propriétaire, en validation immédiate : ce qu'un module sème est visible du serveur d'API que le test interroge. `reset_database` remet la base dans son état d'après les migrations.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

_ARGS: dict[str, Any] = {
    "dbname": "bibliometrie_test",
    "user": os.environ["DB_OWNER_USER"],
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "5432")),
}
if os.environ.get("DB_OWNER_PASSWORD"):
    _ARGS["password"] = os.environ["DB_OWNER_PASSWORD"]


@contextmanager
def owner_pool() -> Iterator[psycopg.Cursor[dict[str, Any]]]:
    """Curseur sur la base de test, en validation immédiate, fermé à la sortie."""
    conn = psycopg.connect(**_ARGS, row_factory=dict_row)
    conn.autocommit = True
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur
    finally:
        conn.close()


# Contenu posé par les migrations : le schéma `ref`, la version Alembic et les réglages par défaut de `ops.config`.
_REFERENCE_SCHEMAS = ("ref",)
_REFERENCE_TABLES = ("public.alembic_version", "ops.config")

type ConfigRow = tuple[str, str, str | None]
"""Réglage de `ops.config` : clé, valeur JSON sérialisée, description."""


def config_rows() -> list[ConfigRow]:
    """Réglages de `ops.config`."""
    with owner_pool() as cur:
        cur.execute("SELECT key, value::text AS value, description FROM ops.config")
        return [(r["key"], r["value"], r["description"]) for r in cur.fetchall()]


def reset_database(config: Sequence[ConfigRow]) -> None:
    """Vide toutes les tables hors du contenu posé par les migrations, et remet `ops.config` à `config`."""
    with owner_pool() as cur:
        cur.execute(
            "SELECT format('%%I.%%I', schemaname, tablename) AS name FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
            "AND schemaname <> ALL(%s) AND schemaname || '.' || tablename <> ALL(%s)",
            (list(_REFERENCE_SCHEMAS), list(_REFERENCE_TABLES)),
        )
        tables = [r["name"] for r in cur.fetchall()]
        cur.execute(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
        cur.execute("DELETE FROM ops.config")
        cur.executemany(
            "INSERT INTO ops.config (key, value, description) VALUES (%s, %s::jsonb, %s)", config
        )
