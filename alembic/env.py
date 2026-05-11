"""Configuration Alembic — branchée sur la MetaData et les settings du projet.

`target_metadata` pointe vers `infrastructure.db.tables.metadata` pour
permettre `alembic revision --autogenerate`.

L'URL de connexion est construite depuis `infrastructure.settings`
(mêmes vars d'env que `infrastructure/db/connection.py`). Le driver
est `postgresql+psycopg` (psycopg3), aligné avec `infrastructure/db/engine.py`.

Si `BIBLIOMETRIE_SANDBOX=1` est défini, bascule sur la base sandbox
(cohérent avec `get_connection`).
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from infrastructure.db.connection import SANDBOX_DB_NAME
from infrastructure.db.tables import metadata
from infrastructure.settings import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _build_url() -> str:
    db_name = SANDBOX_DB_NAME if os.environ.get("BIBLIOMETRIE_SANDBOX") == "1" else settings.db_name
    return (
        f"postgresql+psycopg://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{db_name}"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_build_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    ini_section = config.get_section(config.config_ini_section, {})
    ini_section["sqlalchemy.url"] = _build_url()
    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
