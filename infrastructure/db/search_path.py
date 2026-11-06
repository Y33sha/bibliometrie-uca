"""Contrôle du `search_path` de la base.

Les requêtes SQL nomment les tables sans leur schéma, et dépendent donc du `search_path` de la base. Les migrations posent ce réglage ; `pg_restore` le recrée seulement avec `--create`.
"""

from sqlalchemy import Engine, text

from infrastructure.db.tables import metadata


def check_search_path(engine: Engine) -> None:
    """Vérifie que le `search_path` d'une connexion de `engine` couvre les schémas des tables déclarées.

    Raises:
        RuntimeError: un schéma manque au `search_path`.
    """
    expected = {table.schema for table in metadata.tables.values() if table.schema}
    with engine.connect() as conn:
        database, schemas = conn.execute(
            text("SELECT current_database(), current_schemas(false)")
        ).one()
    missing = sorted(expected - set(schemas))
    if missing:
        raise RuntimeError(
            f"Le search_path de la base {database} omet les schémas {', '.join(missing)}. "
            "Les migrations posent ce réglage de la base ; pg_restore le recrée seulement avec --create."
        )
