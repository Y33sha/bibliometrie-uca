"""Configuration Alembic — branchée sur la MetaData et les settings du projet.

`target_metadata` pointe vers `infrastructure.db.tables.metadata` pour
permettre `alembic revision --autogenerate`.

L'URL de connexion est construite depuis `infrastructure.settings`,
avec driver `postgresql+psycopg` (psycopg3) aligné sur
`infrastructure/db/engine.py`.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from infrastructure.db.tables import metadata
from infrastructure.settings import settings

config = context.config

# `fileConfig` reconfigure le logging du processus et désactive les loggers déjà créés. Un
# appelant programmatique (fixture pytest) pose `configure_logger = False` pour garder le sien.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = metadata


def _include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    """Écarte de la comparaison les objets que la MetaData du projet ne modélise pas.

    `infrastructure/db/tables.py` sert au query building, qui ne connaît que tables et colonnes. Les clés étrangères et les index n'y sont pas déclarés : sans ce filtre, autogenerate proposerait de supprimer de la base tous ceux qu'elle porte. Les uns comme les autres s'écrivent à la main dans la migration, seule source de vérité du schéma.
    """
    return type_ not in ("foreign_key_constraint", "index")


def _build_url() -> str:
    # Permet à un caller (ex. fixture pytest) d'imposer une URL via
    # `cfg.set_main_option("sqlalchemy.url", ...)`. Sinon, on construit
    # depuis les settings du projet.
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return (
        f"postgresql+psycopg://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_build_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
