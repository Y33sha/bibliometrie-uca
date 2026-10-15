# STATUS: recurring (dev)
"""Applique les migrations Alembic à la base par défaut, puis à la base de chaque instance de `instances/`.

Usage :
    migrate_all

Chaque base se migre dans un processus `alembic upgrade head` à part, avec `BIBLIO_INSTANCE` posée sur l'instance : les réglages de la base se lisent au chargement du processus. Alembic écrit son journal dans le terminal. La commande s'arrête au premier échec.
"""

import os
import subprocess
import sys

from infrastructure import PROJECT_ROOT


def instance_names() -> list[str]:
    """Instances de `instances/` qui ont un `instance.env`, par ordre alphabétique."""
    return sorted(p.parent.name for p in (PROJECT_ROOT / "instances").glob("*/instance.env"))


def _upgrade(instance: str | None) -> int:
    """`alembic upgrade head` sur la base de `instance`, ou sur la base par défaut quand `instance` est vide. Rend le code de sortie."""
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
        returncode = _upgrade(instance)
        if returncode != 0:
            sys.exit(returncode)


if __name__ == "__main__":
    main()
