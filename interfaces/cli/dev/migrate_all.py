# STATUS: recurring (dev)
"""Applique les migrations Alembic à la base par défaut, puis à la base de chaque instance de `instances/`.

Usage :
    migrate_all

Chaque base se migre dans un processus `alembic upgrade head` à part, avec `BIBLIO_INSTANCE` posée sur l'instance : les réglages de la base se lisent au chargement du processus. Alembic écrit son journal dans le terminal. Une instance dont la base n'existe pas est sautée. La commande s'arrête au premier échec.
"""

import os
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy import text

from infrastructure import PROJECT_ROOT
from infrastructure.db.engine import get_sync_engine


def instance_names() -> list[str]:
    """Renvoie les instances de `instances/` pourvues d'un `instance.env`, par ordre alphabétique."""
    return sorted(p.parent.name for p in (PROJECT_ROOT / "instances").glob("*/instance.env"))


def _database(instance: str) -> str | None:
    """Renvoie la base de l'instance, d'après son `instance.env`."""
    return dotenv_values(PROJECT_ROOT / "instances" / instance / "instance.env").get("DB_NAME")


def _exists(database: str | None) -> bool:
    """Renvoie vrai quand la base `database` existe sur le serveur."""
    with get_sync_engine().connect() as conn:
        return bool(
            conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"),
                {"name": database},
            ).scalar()
        )


def _upgrade(instance: str | None) -> int:
    """Lance `alembic upgrade head` sur la base de `instance`, ou sur la base par défaut quand `instance` est vide. Renvoie le code de sortie."""
    env = {key: value for key, value in os.environ.items() if key != "BIBLIO_INSTANCE"}
    if instance:
        env["BIBLIO_INSTANCE"] = instance
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    ).returncode


def main() -> None:
    for instance in [None, *instance_names()]:
        print(f"── Base {instance or 'par défaut'}", flush=True)
        if instance and not _exists(database := _database(instance)):
            print(
                f"Base {database} absente : instance sautée (create_instance la crée).", flush=True
            )
            continue
        returncode = _upgrade(instance)
        if returncode != 0:
            sys.exit(returncode)


if __name__ == "__main__":
    main()
