"""Configuration Alembic — branchée sur la MetaData et les settings du projet.

`target_metadata` pointe vers `infrastructure.db.tables.metadata` pour
permettre `alembic revision --autogenerate`.

L'URL de connexion est construite depuis `infrastructure.settings`,
avec driver `postgresql+psycopg` (psycopg3) aligné sur
`infrastructure/db/engine.py`.

Quand une exécution en ligne joue au moins une migration et laisse la base à la tête, les droits des rôles de l'API et du pipeline sont réappliqués (`infrastructure/db/grants.sql`), si ces rôles existent. `grants.sql` décrit le schéma de la tête.
"""

from collections.abc import Collection, Mapping
from logging.config import fileConfig

from alembic.runtime.migration import MigrationContext, MigrationInfo
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool

from alembic import context
from infrastructure.db.engine import db_url
from infrastructure.db.grants import apply_grants
from infrastructure.db.tables import metadata

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


_PROJECT_SCHEMAS = {table.schema for table in metadata.tables.values()}


def _include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Limite la comparaison aux schémas des tables du projet et au schéma par défaut."""
    return type_ != "schema" or name is None or name in _PROJECT_SCHEMAS


# Les migrations se connectent avec `public` pour seul `search_path` : le schéma par défaut ne
# rend alors visibles que les objets de `public`, et chaque table se compare sous son schéma.
# Une migration écrite à la main qualifie donc ses tables par leur schéma.
_CONNECT_ARGS = {"options": "-c search_path=public"}


def _build_url() -> str:
    # Permet à un caller (ex. fixture pytest) d'imposer une URL via
    # `cfg.set_main_option("sqlalchemy.url", ...)`. Sinon, on construit
    # depuis les settings du projet.
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    # Les migrations sont seules à modifier la structure : elles se connectent sous le
    # propriétaire du schéma, que rien d'autre ne porte.
    return db_url("owner").render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=_build_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
        include_schemas=True,
        include_name=_include_name,
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
        connect_args=_CONNECT_ARGS,
    )
    applied: list[MigrationInfo] = []

    def record_applied(
        ctx: MigrationContext,
        step: MigrationInfo,
        heads: Collection[object],
        run_args: Mapping[str, object],
    ) -> None:
        applied.append(step)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object,
            include_schemas=True,
            include_name=_include_name,
            on_version_apply=record_applied,
        )
        with context.begin_transaction():
            context.run_migrations()
            # Une migration qui crée ou recrée une table lui laisse les seuls privilèges par défaut : les droits de `grants.sql` sont réalignés dans la même transaction.
            heads = set(ScriptDirectory.from_config(config).get_heads())
            if applied and set(context.get_context().get_current_heads()) == heads:
                apply_grants(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
