# STATUS: recurring (dev)
"""Crée la base de l'instance désignée par `BIBLIO_INSTANCE` : base, migrations, rôles de connexion, seed commun, seed d'établissement.

Usage :
    BIBLIO_INSTANCE=lorraine python -m interfaces.cli.dev.create_instance [--reseed]

Le seed d'établissement est `instances/<nom>/seed.sql`, à côté de `instance.env`. Le script s'arrête si la base existe déjà. `--reseed` vise une base existante encore vide de documents : il applique les migrations, recharge le seed d'établissement et recalcule les structures des périmètres.
"""

import argparse
import os
import subprocess
from pathlib import Path

from alembic.command import upgrade
from alembic.config import Config
from sqlalchemy import text

from infrastructure import INSTANCE_ENV_FILE, PROJECT_ROOT
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.settings import settings
from interfaces.cli.dev.pg_tools import owner_connection_args, owner_env, resolve_pg_tool
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures

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


def instance_scripts(seed: Path, *, reseed: bool) -> list[Path]:
    """Scripts SQL joués après les migrations : rôles, seed commun et seed d'établissement, ou le seul seed d'établissement au rechargement."""
    if reseed:
        return [seed]
    return [_DB_DIR / "roles.sql", _DB_DIR / "seed.sql", seed]


def _ensure_not_harvested() -> None:
    """Lève `SystemExit` quand `staging` contient des documents : le seed vide `structures`, et la suppression en cascade emporterait les rattachements calculés par le pipeline."""
    with get_sync_engine().connect() as conn:
        if conn.execute(text("SELECT EXISTS (SELECT 1 FROM staging)")).scalar():
            raise SystemExit(
                f"La base {settings.db_name} contient des documents moissonnés : rechargement refusé."
            )


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
    parser = argparse.ArgumentParser(description="Crée la base d'une instance")
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="Base existante : applique les migrations et recharge le seed d'établissement",
    )
    args = parser.parse_args()

    seed = instance_seed(INSTANCE_ENV_FILE)
    if args.reseed:
        _ensure_not_harvested()
    else:
        log.info("Création de la base %s", settings.db_name)
        _create_database(settings.db_name)
    log.info("Migrations")
    _migrate()
    for script in instance_scripts(seed, reseed=args.reseed):
        _run_psql(script)
    # Les lectures de l'API passent par les structures des périmètres du seed (`perimeter_structures`).
    with get_sync_engine().begin() as conn:
        refresh_perimeter_structures(conn)
    log.info("Instance %s chargée sur la base %s", seed.parent.name, settings.db_name)


if __name__ == "__main__":
    main()
