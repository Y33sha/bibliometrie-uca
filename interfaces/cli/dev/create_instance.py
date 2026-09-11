# STATUS: recurring (dev)
"""Crée la base de l'instance désignée par `BIBLIO_INSTANCE` : base, migrations, rôles de connexion, seed commun, seed d'établissement.

Usage :
    BIBLIO_INSTANCE=lorraine python -m interfaces.cli.dev.create_instance

Le seed d'établissement est `instances/<nom>/seed.sql`, à côté de `instance.env`. Le script s'arrête si la base existe déjà.
"""

import os
import subprocess
from pathlib import Path

from alembic.command import upgrade
from alembic.config import Config

from infrastructure import INSTANCE_ENV_FILE, PROJECT_ROOT
from infrastructure.observability.log import setup_logger
from infrastructure.settings import settings
from interfaces.cli.dev.pg_tools import owner_connection_args, owner_env, resolve_pg_tool

log = setup_logger("create_instance", os.path.dirname(__file__))

_DB_DIR = PROJECT_ROOT / "infrastructure" / "db"


def instance_seed(instance_env_file: Path | None) -> Path:
    """Seed d'établissement de l'instance, rangé à côté de son `instance.env`.

    Lève `SystemExit` sans instance désignée ou sans seed : la base créée n'aurait sinon aucune structure.
    """
    if instance_env_file is None:
        raise SystemExit("BIBLIO_INSTANCE doit désigner l'instance à créer.")
    seed = instance_env_file.parent / "seed.sql"
    if not seed.is_file():
        raise SystemExit(f"Seed d'établissement absent : {seed}")
    return seed


def _create_database(name: str) -> None:
    """Crée la base `name`, possédée par le propriétaire du schéma. Échoue si elle existe."""
    subprocess.run(
        [resolve_pg_tool("createdb"), *owner_connection_args(), name],
        env=owner_env(),
        check=True,
    )


def _migrate() -> None:
    """Applique les migrations Alembic à la base de l'instance."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    # `fileConfig` désactiverait sinon le logger de ce script.
    config.attributes["configure_logger"] = False
    upgrade(config, "head")


def _run_psql(script: Path) -> None:
    """Joue `script` sur la base de l'instance, sous le propriétaire du schéma."""
    log.info("Chargement de %s", script)
    subprocess.run(
        [
            resolve_pg_tool("psql"),
            *owner_connection_args(),
            "-d",
            settings.db_name,
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            # Les résultats des requêtes (recalage des séquences) encombrent le journal ; les erreurs passent par stderr.
            "-o",
            os.devnull,
            "-f",
            str(script),
        ],
        env=owner_env(),
        check=True,
    )


def main() -> None:
    seed = instance_seed(INSTANCE_ENV_FILE)
    log.info("Création de la base %s", settings.db_name)
    _create_database(settings.db_name)
    log.info("Migrations")
    _migrate()
    for script in (_DB_DIR / "roles.sql", _DB_DIR / "seed.sql", seed):
        _run_psql(script)
    log.info("Instance %s créée sur la base %s", seed.parent.name, settings.db_name)


if __name__ == "__main__":
    main()
