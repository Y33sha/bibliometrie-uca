# STATUS: recurring (dev)
"""Applique les migrations Alembic à la base par défaut, puis à la base de chaque instance de `instances/`.

Usage :
    migrate_all

Chaque base se migre dans un processus `alembic upgrade head` à part, avec `BIBLIO_INSTANCE` posée sur l'instance : les réglages de la base se lisent au chargement du processus. La commande s'arrête au premier échec.
"""

import os
import subprocess
import sys

from infrastructure import PROJECT_ROOT


def instance_names() -> list[str]:
    """Instances de `instances/` qui ont un `instance.env`, par ordre alphabétique."""
    return sorted(p.parent.name for p in (PROJECT_ROOT / "instances").glob("*/instance.env"))


def _alembic(command: list[str], instance: str | None) -> subprocess.CompletedProcess[str]:
    """Commande Alembic sur la base de `instance`, ou sur la base par défaut quand `instance` est vide."""
    env = {key: value for key, value in os.environ.items() if key != "BIBLIO_INSTANCE"}
    if instance:
        env["BIBLIO_INSTANCE"] = instance
    return subprocess.run(
        [sys.executable, "-m", "alembic", *command],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _revision(instance: str | None) -> str:
    """Révision courante de la base, telle qu'`alembic current` l'affiche."""
    return _alembic(["current"], instance).stdout.strip() or "aucune"


def main() -> None:
    for instance in [None, *instance_names()]:
        label = instance or "défaut"
        before = _revision(instance)
        result = _alembic(["upgrade", "head"], instance)
        if result.returncode != 0:
            print(f"{label} : échec de la migration depuis {before}", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(result.returncode)
        after = _revision(instance)
        print(f"{label} : {before} → {after}" if after != before else f"{label} : {after}")


if __name__ == "__main__":
    main()
