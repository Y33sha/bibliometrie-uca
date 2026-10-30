"""Connexions à la base de test.

`database_url` donne l'URL de la base de test sous un rôle de connexion. Les tests d'intégration de l'API sèment leur jeu de données sous le propriétaire du schéma, en validation immédiate : les données semées par un module sont visibles du serveur d'API interrogé par le test. `owner_connection` ouvre cette connexion SQLAlchemy, `owner_pool` un curseur psycopg sur elle. `reset_database` remet la base dans son état d'après les migrations.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from functools import cache
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from sqlalchemy import URL, Connection, Engine, create_engine

# Charge .env avant de lire os.environ, comme infrastructure/__init__.py : `pytest` lancé depuis un shell sans DB_OWNER_USER exporté trouve la valeur dans le .env du projet.
load_dotenv(pathlib.Path(__file__).resolve().parents[3] / ".env")

DB_NAME = "bibliometrie_test"
DB_OWNER_USER = os.environ["DB_OWNER_USER"]
DB_OWNER_PASSWORD = os.environ.get("DB_OWNER_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))


def database_url(*, identity: str = "pipeline") -> URL:
    """Renvoie l'URL SQLAlchemy de la base de test, sous le rôle `identity` (`pipeline`, `app` ou `owner`).

    Le propriétaire du schéma sert aux migrations et au semis des tests d'API. Les fixtures de données passent par le rôle du pipeline, celles qui exercent une opération de l'API par le rôle de l'API.
    """
    from infrastructure.settings import settings

    if identity == "owner":
        username, password = DB_OWNER_USER, DB_OWNER_PASSWORD
    else:
        username = getattr(settings, f"db_{identity}_user")
        password = getattr(settings, f"db_{identity}_password").get_secret_value()
    return URL.create(
        drivername="postgresql+psycopg",
        username=username,
        password=password or None,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
    )


@cache
def _owner_engine() -> Engine:
    """Renvoie l'engine du propriétaire du schéma en `AUTOCOMMIT`, créé au premier appel."""
    return create_engine(database_url(identity="owner"), isolation_level="AUTOCOMMIT")


@contextmanager
def owner_connection() -> Iterator[Connection]:
    """Ouvre une connexion SQLAlchemy sous le propriétaire du schéma, en validation immédiate, rendue au pool à la sortie."""
    with _owner_engine().connect() as conn:
        yield conn


@contextmanager
def owner_pool() -> Iterator[psycopg.Cursor[dict[str, Any]]]:
    """Ouvre un curseur psycopg à lignes en dictionnaire sur une connexion `owner_connection`, fermé à la sortie."""
    with owner_connection() as conn:
        with conn.connection.driver_connection.cursor(row_factory=dict_row) as cur:
            yield cur


# Contenu posé par les migrations : le schéma `ref`, la version Alembic, les rôles et les réglages par défaut de `ops.config`.
_REFERENCE_SCHEMAS = ("ref",)
_REFERENCE_TABLES = ("public.alembic_version", "ops.config", "ops.roles")

type ConfigRow = tuple[str, str, str | None]
"""Réglage de `ops.config` : clé, valeur JSON sérialisée, description."""


def config_rows() -> list[ConfigRow]:
    """Renvoie les réglages de `ops.config`."""
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
